"""SQLite database layer for AgentTrafficCop."""

from __future__ import annotations
import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

logger = logging.getLogger("agenttrafficcop.db")

_db_path_env = os.getenv("ATC_DB_PATH")
DB_PATH = Path(_db_path_env) if _db_path_env else Path(__file__).resolve().parent.parent / "agenttrafficcop.db"

try:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
except OSError as e:
    logger.critical("db_parent_dir_unavailable path=%s error=%s", DB_PATH.parent, e)
    raise

def init_db() -> None:
    with get_db() as conn:
        cursor = conn.cursor()

        # 1. Create Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                webhook_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Safe migrations for Users
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN is_verified BOOLEAN DEFAULT 0;")
            # Auto-verify existing users so they don't get locked out
            cursor.execute("UPDATE users SET is_verified = 1;")
        except sqlite3.OperationalError: pass

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN verification_token TEXT;")
        except sqlite3.OperationalError: pass

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN webhook_url TEXT;")
        except sqlite3.OperationalError: pass

        # 2. Create API Keys table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_hash TEXT UNIQUE NOT NULL,
                fingerprint TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                tier TEXT NOT NULL DEFAULT 'free',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                revoked_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        
        # Safe migration for API Keys
        try:
            cursor.execute("ALTER TABLE api_keys ADD COLUMN name TEXT;")
        except sqlite3.OperationalError: pass

        # Daily usage for chart
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL,
                date TEXT NOT NULL,
                approved INTEGER DEFAULT 0,
                rejected INTEGER DEFAULT 0,
                UNIQUE(fingerprint, date)
            )
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id) WHERE revoked_at IS NULL")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_fingerprint ON api_keys(fingerprint) WHERE revoked_at IS NULL")

        conn.commit()
        logger.info("database_initialized path=%s", DB_PATH)

@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except Exception: pass
    try:
        yield conn
    finally:
        conn.close()

init_db()