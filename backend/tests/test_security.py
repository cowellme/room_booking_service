from types import SimpleNamespace
from app.main import app
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


def test_extracted_routes_are_registered():
    paths = app.openapi()["paths"]
    expected = {
        "/api/auth/register/request-code", "/api/auth/register", "/api/auth/login",
        "/api/auth/password/forgot", "/api/auth/password/reset", "/api/auth/password/change",
        "/api/auth/logout", "/api/auth/me", "/api/profile", "/api/profile/avatar",
        "/api/profile/extra-rooms-guide", "/api/profile/extra-rooms-guide/seen",
        "/api/bookings", "/api/me/bookings", "/api/me/bookings/{booking_id}/cancel",
        "/api/me/booking-series/{series_id}/cancel", "/api/me/bookings/{booking_id}/extra-rooms",
        "/api/me/request-with-file", "/api/me/attachments/{attachment_id}",
        "/api/bookings/{booking_id}/attachments", "/api/booking-series/{series_id}/attachments",
        "/api/attachments/{attachment_id}", "/api/me/notifications",
        "/api/admin/bookings", "/api/admin/bookings/{booking_id}/approve",
        "/api/admin/bookings/{booking_id}/reject",
        "/api/admin/booking-center", "/api/admin/booking-center/{booking_id}",
        "/api/admin/booking-center/{booking_id}/extra-rooms",
        "/api/admin/booking-center/{booking_id}/observers",
        "/api/admin/booking-center/{booking_id}/transfer",
        "/api/admin/booking-center/{booking_id}/comments",
        "/api/admin/booking-center/{booking_id}/comments/{comment_id}/resolve",
        "/api/admin/booking-center/{booking_id}/archive",
        "/api/admin/booking-center/{booking_id}/cancel",
        "/api/admin/booking-center/{booking_id}/status",
        "/api/admin/booking-bulk/archive", "/api/admin/booking-bulk/delete",
        "/api/admin/users/search", "/api/me/observed-bookings",
        "/api/me/observed-bookings/{booking_id}",
        "/api/me/observed-bookings/{booking_id}/comments",
    }
    assert expected <= paths.keys()
