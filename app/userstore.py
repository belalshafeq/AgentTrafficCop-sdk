"""User management."""
from __future__ import annotations
import logging
import secrets
from dataclasses import dataclass
from typing import Optional
from passlib.context import CryptContext
from .db import get_db

logger = logging.getLogger("agenttrafficcop.userstore")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@dataclass(frozen=True)
class User:
    id: int
    email: str
    password_hash: str
    webhook_url: Optional[str] = None
    is_verified: bool = False

class UserStore:
    def create_user(self, email: str, password: str) -> User:
        email = email.lower().strip()
        password_hash = pwd_context.hash(password)
        token = secrets.token_urlsafe(32)
        
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO users (email, password_hash, verification_token) VALUES (?, ?, ?)",
                    (email, password_hash, token)
                )
                conn.commit()
                user_id = cursor.lastrowid
            return User(id=user_id, email=email, password_hash=password_hash, is_verified=False)
        except Exception as e:
            if "UNIQUE constraint failed" in str(e): raise ValueError("Email already registered")
            raise

    def get_user_by_email(self, email: str) -> Optional[User]:
        email = email.lower().strip()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            row = cursor.fetchone()
        if row is None: return None
        return User(
            id=row["id"], email=row["email"], password_hash=row["password_hash"],
            webhook_url=row["webhook_url"], is_verified=bool(row["is_verified"])
        )

    def get_verification_token(self, email: str) -> Optional[str]:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT verification_token FROM users WHERE email = ?", (email,))
            row = cursor.fetchone()
            return row["verification_token"] if row else None

    def verify_email(self, token: str) -> bool:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_verified = 1, verification_token = NULL WHERE verification_token = ?", (token,))
            conn.commit()
            return cursor.rowcount > 0

    def create_api_key(self, user_id: int, tier: str = "free", name: str = "Default") -> str:
        import hashlib
        raw_key = f"atc_live_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        fingerprint = key_hash[:8]
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO api_keys (key_hash, fingerprint, user_id, tier, name) VALUES (?, ?, ?, ?, ?)",
                (key_hash, fingerprint, user_id, tier, name)
            )
            conn.commit()
        return raw_key

    def get_api_keys(self, user_id: int) -> list:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT fingerprint, name, created_at FROM api_keys WHERE user_id = ? AND revoked_at IS NULL", (user_id,))
            return [dict(r) for r in cursor.fetchall()]

    def get_user_tier(self, user_id: int) -> str:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT tier FROM api_keys WHERE user_id = ? AND revoked_at IS NULL LIMIT 1", (user_id,))
            row = cursor.fetchone()
            return row["tier"] if row else "free"

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        try: return pwd_context.verify(plain_password, hashed_password)
        except Exception: return False

    def update_webhook_url(self, user_id: int, url: Optional[str]) -> None:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET webhook_url = ? WHERE id = ?", (url, user_id))
            conn.commit()

    def update_password(self, user_id: int, new_password: str) -> None:
        new_hash = pwd_context.hash(new_password)
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
            conn.commit()

    def delete_user(self, user_id: int) -> None:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM api_keys WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()

user_store = UserStore()