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
if _db_path_env:
    DB_PATH = Path(_db_path_env)
else:
    DB_PATH = Path(__file__).resolve().parent.parent / "agenttrafficcop.db"

try:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
except OSError as e:
    logger.critical(
        "db_parent_dir_unavailable path=%s error=%s "
        "hint='On Render, mount a persistent disk and set "
        "ATC_DB_PATH=/data/agenttrafficcop.db'",
        DB_PATH.parent,
        e,
    )
    raise


def init_db() -> None:
    """Create the tables if they don't exist, and run safe migrations."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                webhook_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # FIX: Safe migration for existing DBs. If webhook_url doesn't exist,
        # this adds it without dropping the table or losing data.
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN webhook_url TEXT;")
            logger.info("db_migration_added_webhook_url")
        except sqlite3.OperationalError:
            pass # Column already exists

        # API Keys table
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

        # Daily usage for the chart
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

        # Indexes for fast lookups
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
    except Exception as e:
        logger.warning("db_pragma_failed error=%s", e)

    try:
        yield conn
    finally:
        conn.close()

init_db()