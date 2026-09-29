"""Runtime configuration, resolved from the environment.

All settings have a safe default for local development. Anything that is a
secret (JWT signing key, seed admin password) MUST be provided in production
via the environment; the defaults here are only meant to let the test suite
and a bare `uvicorn` run without ceremony.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    # Where the SQLite file lives. Never place this inside the TOS/rclone mount.
    db_path: str = os.environ.get("AUTH_DB_PATH", "/data/auth.db")
    # HMAC signing key for session JWTs. MUST be set in production.
    jwt_secret: str = os.environ.get("AUTH_JWT_SECRET", "dev-insecure-change-me")
    # Session lifetime (seconds). Default 7 days.
    token_ttl: int = int(os.environ.get("AUTH_TOKEN_TTL", str(7 * 24 * 3600)))
    # "Remember me" lifetime (seconds). Default 30 days.
    remember_ttl: int = int(os.environ.get("AUTH_REMEMBER_TTL", str(30 * 24 * 3600)))
    cookie_name: str = os.environ.get("AUTH_COOKIE_NAME", "veai_session")
    # Set true behind HTTPS (production). Local http dev keeps it false.
    cookie_secure: bool = _bool("AUTH_COOKIE_SECURE", False)
    cookie_samesite: str = os.environ.get("AUTH_COOKIE_SAMESITE", "lax")
    # Seed admin account, created once on first boot if the table is empty.
    seed_admin_user: str = os.environ.get("AUTH_ADMIN_USER", "admin")
    seed_admin_password: str = os.environ.get("AUTH_ADMIN_PASSWORD", "admin")

    @staticmethod
    def from_env() -> "Config":
        # Re-read env at call time so tests can monkeypatch os.environ.
        return Config(
            db_path=os.environ.get("AUTH_DB_PATH", "/data/auth.db"),
            jwt_secret=os.environ.get("AUTH_JWT_SECRET", "dev-insecure-change-me"),
            token_ttl=int(os.environ.get("AUTH_TOKEN_TTL", str(7 * 24 * 3600))),
            remember_ttl=int(os.environ.get("AUTH_REMEMBER_TTL", str(30 * 24 * 3600))),
            cookie_name=os.environ.get("AUTH_COOKIE_NAME", "veai_session"),
            cookie_secure=_bool("AUTH_COOKIE_SECURE", False),
            cookie_samesite=os.environ.get("AUTH_COOKIE_SAMESITE", "lax"),
            seed_admin_user=os.environ.get("AUTH_ADMIN_USER", "admin"),
            seed_admin_password=os.environ.get("AUTH_ADMIN_PASSWORD", "admin"),
        )
