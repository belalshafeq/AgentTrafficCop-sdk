"""User management: creation, lookup, and password verification."""

from __future__ import annotations

import logging
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


class UserStore:
    """Data access object for users."""

    def create_user(self, email: str, password: str) -> User:
        email = email.lower().strip()
        password_hash = pwd_context.hash(password)
        
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                    (email, password_hash)
                )
                conn.commit()
                user_id = cursor.lastrowid
                
            logger.info("user_created email=%s", email)
            return User(id=user_id, email=email, password_hash=password_hash)
            
        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                raise ValueError("Email already registered") from e
            raise

    def get_user_by_email(self, email: str) -> Optional[User]:
        email = email.lower().strip()
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, email, password_hash, webhook_url FROM users WHERE email = ?",
                (email,)
            )
            row = cursor.fetchone()
            
        if row is None:
            return None
            
        return User(
            id=row["id"],
            email=row["email"],
            password_hash=row["password_hash"],
            webhook_url=row["webhook_url"]
        )

    def get_user_tier(self, user_id: int) -> str:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT tier FROM api_keys WHERE user_id = ? AND revoked_at IS NULL LIMIT 1",
                (user_id,)
            )
            row = cursor.fetchone()
            return row["tier"] if row else "free"

    def create_api_key(self, user_id: int, tier: str = "free") -> str:
        import secrets
        import hashlib
        
        raw_key = f"atc_live_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        fingerprint = key_hash[:8]
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO api_keys (key_hash, fingerprint, user_id, tier) 
                VALUES (?, ?, ?, ?)
                """,
                (key_hash, fingerprint, user_id, tier)
            )
            conn.commit()
            
        logger.info("api_key_created user_id=%s tier=%s fingerprint=%s", user_id, tier, fingerprint)
        return raw_key

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        try:
            return pwd_context.verify(plain_password, hashed_password)
        except (ValueError, TypeError):
            logger.warning("password_verify_bad_hash")
            return False

    def update_webhook_url(self, user_id: int, url: Optional[str]) -> None:
        """Save or clear the user's webhook URL."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET webhook_url = ? WHERE id = ?",
                (url, user_id)
            )
            conn.commit()
        logger.info("webhook_url_updated user_id=%s", user_id)

    def delete_user(self, user_id: int) -> None:
        """Wipe the user and all their API keys from the database."""
        with get_db() as conn:
            cursor = conn.cursor()
            # Delete API keys first (Foreign Key constraint)
            cursor.execute("DELETE FROM api_keys WHERE user_id = ?", (user_id,))
            # Delete the user
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
        logger.info("user_deleted user_id=%s", user_id)


user_store = UserStore()