from types import SimpleNamespace
from app.security import admin_read_user, create_session, decode_session, hash_password, verify_password
from app.models import User
from fastapi import HTTPException
import pytest

def test_password_is_hashed_and_verified():
    encoded = hash_password("a-strong-test-password")
    assert encoded != "a-strong-test-password"
    assert verify_password("a-strong-test-password", encoded)
    assert not verify_password("wrong-password", encoded)


def test_admin_read_does_not_require_csrf_header():
    user = User(id=1, email="admin@example.org", full_name="Admin", password_hash="x", role="admin")
    assert admin_read_user(user) is user


def test_admin_read_rejects_regular_user():
    user = User(id=2, email="user@example.org", full_name="User", password_hash="x", role="user")
    with pytest.raises(HTTPException):
        admin_read_user(user)

def test_session_contains_identity_and_csrf():
    token, csrf = create_session(SimpleNamespace(id=42, role="admin"))
    payload = decode_session(token)
    assert payload["sub"] == "42"
    assert payload["role"] == "admin"
    assert payload["csrf"] == csrf
