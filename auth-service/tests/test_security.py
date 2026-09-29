import time

import jwt
import pytest

from app.security import (
    create_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_is_salted_and_verifiable():
    h1 = hash_password("hunter2")
    h2 = hash_password("hunter2")
    assert h1 != h2  # unique salt each time
    assert verify_password("hunter2", h1)
    assert verify_password("hunter2", h2)


def test_verify_rejects_wrong_password():
    h = hash_password("correct-horse")
    assert not verify_password("battery-staple", h)


def test_verify_handles_garbage_gracefully():
    assert not verify_password("x", "not-a-bcrypt-hash")
    assert not verify_password("", hash_password("abc"))


def test_hash_rejects_empty_and_overlong():
    with pytest.raises(ValueError):
        hash_password("")
    with pytest.raises(ValueError):
        hash_password("x" * 73)


def test_token_roundtrip():
    tok = create_token(
        user_id=42, username="alice", is_admin=True, secret="s3cret", ttl=60
    )
    claims = decode_token(tok, secret="s3cret")
    assert claims["sub"] == "42"
    assert claims["username"] == "alice"
    assert claims["is_admin"] is True


def test_token_rejects_wrong_secret():
    tok = create_token(
        user_id=1, username="a", is_admin=False, secret="right", ttl=60
    )
    with pytest.raises(jwt.PyJWTError):
        decode_token(tok, secret="wrong")


def test_token_expiry():
    tok = create_token(
        user_id=1, username="a", is_admin=False, secret="s", ttl=-1
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(tok, secret="s")
