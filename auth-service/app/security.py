"""Password hashing and session-token primitives.

Kept dependency-light and pure so it can be unit-tested without a DB or the
web layer: bcrypt for password storage, PyJWT (HS256) for session tokens.
"""
from __future__ import annotations

import time
from typing import Any

import bcrypt
import jwt

_JWT_ALG = "HS256"


def hash_password(password: str) -> str:
    """Return a bcrypt hash (utf-8 str) for the given plaintext password."""
    if not isinstance(password, str) or password == "":
        raise ValueError("password must be a non-empty string")
    # bcrypt silently truncates at 72 bytes; reject longer to avoid surprises.
    encoded = password.encode("utf-8")
    if len(encoded) > 72:
        raise ValueError("password must be at most 72 bytes")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time check of a plaintext password against a bcrypt hash."""
    if not password or not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_token(
    *, user_id: int, username: str, is_admin: bool, secret: str, ttl: int
) -> str:
    """Issue a signed session JWT carrying identity + expiry."""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "username": username,
        "is_admin": bool(is_admin),
        "iat": now,
        "exp": now + int(ttl),
    }
    return jwt.encode(payload, secret, algorithm=_JWT_ALG)


def decode_token(token: str, *, secret: str) -> dict[str, Any]:
    """Decode + verify a session JWT. Raises jwt.PyJWTError on any problem."""
    return jwt.decode(token, secret, algorithms=[_JWT_ALG])
