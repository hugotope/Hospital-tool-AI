"""
Hospital AI — SQLite database layer
====================================
Manages users and in-memory sessions.
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent / "hospital.db"

# ── In-memory sessions (token → session dict) ────────────────────────────────
_sessions: dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Connection
# ─────────────────────────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# Init
# ─────────────────────────────────────────────────────────────────────────────

def init_db() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                username     TEXT    UNIQUE NOT NULL,
                name         TEXT    NOT NULL,
                email        TEXT    DEFAULT '',
                password_hash TEXT   NOT NULL,
                role         TEXT    DEFAULT 'user',
                created_at   TEXT    DEFAULT (datetime('now')),
                is_active    INTEGER DEFAULT 1
            );
        """)
        # Seed default admin
        if not conn.execute("SELECT id FROM users WHERE username='admin'").fetchone():
            conn.execute(
                "INSERT INTO users (username,name,email,password_hash,role) VALUES (?,?,?,?,?)",
                ("admin", "Administrador", "admin@hospital.com", hash_password("1234"), "admin"),
            )
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Password hashing
# ─────────────────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, stored_hash: str) -> bool:
    return hash_password(password) == stored_hash


# ─────────────────────────────────────────────────────────────────────────────
# User CRUD
# ─────────────────────────────────────────────────────────────────────────────

def get_user_by_username(username: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? AND is_active=1", (username,)
        ).fetchone()
        return dict(row) if row else None


def get_all_users() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id,username,name,email,role,created_at,is_active FROM users ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def create_user(username: str, name: str, email: str, password: str, role: str = "user") -> dict:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO users (username,name,email,password_hash,role) VALUES (?,?,?,?,?)",
            (username, name, email, hash_password(password), role),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id,username,name,email,role,created_at FROM users WHERE username=?",
            (username,),
        ).fetchone()
        return dict(row)


def deactivate_user(user_id: int) -> bool:
    """Soft-delete: sets is_active=0. Admin cannot be deactivated."""
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE users SET is_active=0 WHERE id=? AND username!='admin'", (user_id,)
        )
        conn.commit()
        return cur.rowcount > 0


def update_password(user_id: int, new_password: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (hash_password(new_password), user_id),
        )
        conn.commit()
        return cur.rowcount > 0


# ─────────────────────────────────────────────────────────────────────────────
# Session management
# ─────────────────────────────────────────────────────────────────────────────

def create_session(user_id: int, username: str, role: str) -> str:
    token = str(uuid.uuid4())
    _sessions[token] = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "expires": datetime.now() + timedelta(hours=8),
    }
    return token


def get_session(token: str) -> Optional[dict]:
    session = _sessions.get(token)
    if session and session["expires"] > datetime.now():
        return session
    _sessions.pop(token, None)
    return None


def delete_session(token: str) -> None:
    _sessions.pop(token, None)
