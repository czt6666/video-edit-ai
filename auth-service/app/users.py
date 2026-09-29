"""User repository/service: all DB access + auth logic lives here.

Functions take an open sqlite3.Connection so they are trivial to unit-test
against an in-memory database. The web layer (main.py) owns connection
lifecycle and HTTP concerns; this module owns correctness.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any, Optional

from .security import hash_password, verify_password

# Usernames: keep them simple + shell/URL safe.
_MIN_USERNAME = 1
_MAX_USERNAME = 64
# Low-friction: any non-empty password is accepted (this is a small team tool,
# not a public service). bcrypt's 72-byte ceiling is the only hard limit.
_MIN_PASSWORD = 1


class UserError(Exception):
    """Base class for expected, user-facing errors."""


class DuplicateUser(UserError):
    pass


class UserNotFound(UserError):
    pass


class ValidationError(UserError):
    pass


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "is_admin": bool(row["is_admin"]),
        "created_at": row["created_at"],
    }


def _validate_username(username: Any) -> str:
    if not isinstance(username, str):
        raise ValidationError("username is required")
    username = username.strip()
    if not (_MIN_USERNAME <= len(username) <= _MAX_USERNAME):
        raise ValidationError("username must be 1-64 characters")
    if not all((c.isascii() and c.isalnum()) or c in "._-" for c in username):
        raise ValidationError("username may contain only ASCII letters, digits, . _ -")
    return username


def _validate_password(password: Any) -> str:
    if not isinstance(password, str) or len(password) < _MIN_PASSWORD:
        raise ValidationError(f"password must be at least {_MIN_PASSWORD} characters")
    if len(password.encode("utf-8")) > 72:
        raise ValidationError("password must be at most 72 bytes")
    return password


def create_user(
    conn: sqlite3.Connection,
    username: str,
    password: str,
    *,
    is_admin: bool = False,
) -> dict[str, Any]:
    username = _validate_username(username)
    password = _validate_password(password)
    now = int(time.time())
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) "
            "VALUES (?, ?, ?, ?)",
            (username, hash_password(password), 1 if is_admin else 0, now),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise DuplicateUser(f"user '{username}' already exists") from exc
    return {
        "id": cur.lastrowid,
        "username": username,
        "is_admin": bool(is_admin),
        "created_at": now,
    }


def get_user_by_id(conn: sqlite3.Connection, user_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT id, username, is_admin, created_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    return _row_to_dict(row)


def get_user_by_name(conn: sqlite3.Connection, username: str) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT id, username, is_admin, created_at FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    return _row_to_dict(row)


def list_users(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, username, is_admin, created_at FROM users ORDER BY id"
    ).fetchall()
    return [d for d in (_row_to_dict(r) for r in rows) if d is not None]


def count_users(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"])


def delete_user(conn: sqlite3.Connection, user_id: int) -> None:
    # Refuse to delete the last remaining admin: that would lock everyone out.
    target = conn.execute(
        "SELECT is_admin FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if target is None:
        raise UserNotFound(f"user {user_id} not found")
    if target["is_admin"]:
        admins = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE is_admin = 1"
        ).fetchone()["n"]
        if admins <= 1:
            raise ValidationError("cannot delete the last remaining admin")
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()


def authenticate(
    conn: sqlite3.Connection, username: Any, password: Any
) -> Optional[dict[str, Any]]:
    """Return the user dict on valid credentials, else None.

    Runs a hash verification even when the user does not exist to keep the
    response time roughly uniform (mitigates username enumeration by timing).
    """
    if not isinstance(username, str) or not isinstance(password, str):
        return None
    row = conn.execute(
        "SELECT id, username, password_hash, is_admin, created_at "
        "FROM users WHERE username = ?",
        (username.strip(),),
    ).fetchone()
    if row is None:
        # Dummy verify against a fixed hash to equalize timing.
        verify_password(password, "$2b$12$" + "." * 53)
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "is_admin": bool(row["is_admin"]),
        "created_at": row["created_at"],
    }


def seed_admin(conn: sqlite3.Connection, username: str, password: str) -> None:
    """Create the initial admin account if the users table is empty."""
    if count_users(conn) == 0:
        create_user(conn, username, password, is_admin=True)
