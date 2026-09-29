import os
import sqlite3

import pytest

from app.config import Config
from app.db import connect, init_db


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """A fresh in-memory database with schema applied, per test."""
    c = connect(":memory:")
    init_db(c)
    yield c
    c.close()


@pytest.fixture()
def config(tmp_path) -> Config:
    """A Config pointing at a temp-file DB (so multiple connections share it)."""
    return Config(
        db_path=str(tmp_path / "auth.db"),
        jwt_secret="test-secret",
        token_ttl=3600,
        remember_ttl=7200,
        cookie_name="veai_session",
        cookie_secure=False,
        cookie_samesite="lax",
        seed_admin_user="admin",
        seed_admin_password="admin-pass",
    )


@pytest.fixture()
def client(config):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(config)
    with TestClient(app) as c:
        yield c
