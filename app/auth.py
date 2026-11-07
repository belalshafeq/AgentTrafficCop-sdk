"""Authentication routes: Register, Login, Key Management, and Password Reset."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, Field, field_validator

from .config import settings
from .db import get_db
from .middleware import _RateLimiter, _client_key
from .schemas import UsageResponse, WebhookUpdate, KeyCreate
from .usage import (
    snapshot, 
    _resolve_usage_key, 
    get_tier_and_limit,
    get_api_key_created_at,
)
from .userstore import user_store, User
from .emailer import send_password_reset_email, send_verification_email

logger = logging.getLogger("agenttrafficcop.auth")
router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")

_auth_limiter = _RateLimiter(
    max_per_window=10,
    window_seconds=60,
    max_clients=10_000,
)


def _enforce_auth_rate_limit(request: Request) -> None:
    ip = _client_key(request)
    allowed, retry_after = _auth_limiter.check(ip)
    if not allowed:
        logger.warning("auth_rate_limit_exceeded ip=%s path=%s", ip, request.url.path)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many authentication attempts. Retry in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def _bcrypt_byte_limit(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 72:
            raise ValueError("password must be at most 72 bytes when UTF-8 encoded")
        return v


class Token(BaseModel):
    access_token: str
    token_type: str
    api_key: str | None = None


class UserProfile(BaseModel):
    id: int
    email: str
    tier: str
    api_key_fingerprint: str | None = None
    webhook_url: str | None = None
    is_verified: bool = False
    api_keys: list = []


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = user_store.get_user_by_email(email)
    if user is None:
        raise credentials_exception
    return user


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/v1/auth/register", response_model=Token, status_code=201)
async def register(request: Request, body: UserRegister):
    _enforce_auth_rate_limit(request)
    try:
        user = user_store.create_user(body.email, body.password)
        token = user_store.get_verification_token(user.email)
        if token:
            send_verification_email(user.email, token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    access_token = create_access_token(data={"sub": user.email})
    return Token(access_token=access_token, token_type="bearer")


@router.post("/v1/auth/login", response_model=Token)
async def login(request: Request, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    _enforce_auth_rate_limit(request)
    user = user_store.get_user_by_email(form_data.username)
    if not user or not user_store.verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    return Token(access_token=create_access_token(data={"sub": user.email}), token_type="bearer")


@router.post("/v1/auth/verify-email")
async def verify_email(request: Request, body: dict):
    token = body.get("token")
    if not token or not user_store.verify_email(token):
        raise HTTPException(status_code=400, detail="Invalid or expired token.")
    return {"message": "Email verified successfully."}


@router.get("/v1/auth/me", response_model=UserProfile)
async def get_me(current_user: Annotated[User, Depends(get_current_user)]):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT tier, fingerprint FROM api_keys WHERE user_id = ? AND revoked_at IS NULL LIMIT 1", (current_user.id,))
        row = cursor.fetchone()

    keys = user_store.get_api_keys(current_user.id)
    
    return UserProfile(
        id=current_user.id,
        email=current_user.email,
        tier=row["tier"] if row else "free",
        api_key_fingerprint=row["fingerprint"] if row else None,
        webhook_url=current_user.webhook_url,
        is_verified=current_user.is_verified,
        api_keys=keys,
    )


@router.get("/v1/auth/usage", response_model=UsageResponse)
async def get_dashboard_usage(current_user: Annotated[User, Depends(get_current_user)]):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT fingerprint FROM api_keys WHERE user_id = ? AND revoked_at IS NULL LIMIT 1", (current_user.id,))
        row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No active API keys found.")
    return UsageResponse(**snapshot(row["fingerprint"]).to_dict())


@router.post("/v1/auth/keys", response_model=dict)
async def create_new_key(body: KeyCreate, request: Request, current_user: Annotated[User, Depends(get_current_user)]):
    _enforce_auth_rate_limit(request)
    if not current_user.is_verified:
        raise HTTPException(status_code=403, detail="Please verify your email before generating API keys.")

    tier = user_store.get_user_tier(current_user.id)
    max_keys = 1 if tier == "free" else (5 if tier == "pro" else 999999)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM api_keys WHERE user_id = ? AND revoked_at IS NULL", (current_user.id,))
        current_count = cursor.fetchone()["count"]

    if current_count >= max_keys:
        raise HTTPException(status_code=400, detail=f"API key limit reached for the {tier} tier ({max_keys} keys).")

    raw_key = user_store.create_api_key(current_user.id, tier=tier, name=body.name)
    _resolve_usage_key.cache_clear()
    get_tier_and_limit.cache_clear()
    get_api_key_created_at.cache_clear()
    return {"api_key": raw_key, "message": "Save this key. It will not be shown again."}


@router.delete("/v1/auth/keys/{fingerprint}")
async def revoke_specific_key(fingerprint: str, request: Request, current_user: Annotated[User, Depends(get_current_user)]):
    _enforce_auth_rate_limit(request)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE api_keys SET revoked_at = CURRENT_TIMESTAMP WHERE fingerprint = ? AND user_id = ? AND revoked_at IS NULL",
            (fingerprint, current_user.id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Key not found or already revoked.")
            
    _resolve_usage_key.cache_clear()
    get_tier_and_limit.cache_clear()
    get_api_key_created_at.cache_clear()
    return {"status": "success", "message": "API key revoked."}


@router.delete("/v1/auth/keys")
async def revoke_all_keys(request: Request, current_user: Annotated[User, Depends(get_current_user)]):
    _enforce_auth_rate_limit(request)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE api_keys SET revoked_at = CURRENT_TIMESTAMP WHERE user_id = ? AND revoked_at IS NULL", (current_user.id,))
        conn.commit()
    _resolve_usage_key.cache_clear()
    get_tier_and_limit.cache_clear()
    get_api_key_created_at.cache_clear()
    return {"status": "success", "message": "All API keys revoked."}


@router.post("/v1/auth/webhook")
async def update_webhook(body: WebhookUpdate, current_user: Annotated[User, Depends(get_current_user)]):
    url_str = str(body.webhook_url) if body.webhook_url else None
    user_store.update_webhook_url(current_user.id, url_str)
    return {"status": "success", "webhook_url": url_str}


@router.delete("/v1/auth/account")
async def delete_account(request: Request, current_user: Annotated[User, Depends(get_current_user)]):
    _enforce_auth_rate_limit(request)
    _resolve_usage_key.cache_clear()
    get_tier_and_limit.cache_clear()
    get_api_key_created_at.cache_clear()
    user_store.delete_user(current_user.id)
    return {"status": "success", "message": "Account permanently deleted."}


@router.post("/v1/auth/forgot-password")
async def forgot_password(request: Request, body: dict):
    _enforce_auth_rate_limit(request)
    email = body.get("email", "").lower().strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required.")
        
    user = user_store.get_user_by_email(email)
    if user:
        reset_token = jwt.encode(
            {"sub": user.email, "action": "reset", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        send_password_reset_email(user.email, reset_token)
        
    return {"message": "If that email is registered, a reset link has been sent."}


@router.post("/v1/auth/reset-password")
async def reset_password(request: Request, body: dict):
    _enforce_auth_rate_limit(request)
    token = body.get("token")
    new_password = body.get("new_password")
    if not token or not new_password:
        raise HTTPException(status_code=400, detail="Token and new password required.")
        
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("action") != "reset":
            raise HTTPException(status_code=400, detail="Invalid token.")
        email = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=400, detail="Token is invalid or expired.")

    user = user_store.get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
        
    user_store.update_password(user.id, new_password)
    return {"message": "Password updated successfully."}