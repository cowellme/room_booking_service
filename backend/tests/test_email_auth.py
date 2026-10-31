"""Registration by corporate email with a code, password reset/change and
per-account brute-force protection (one shared office IP must not lock everyone)."""
from dataclasses import replace
from datetime import timedelta
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import get_db
from app.models import Base, EmailCode, User
from app.security import hash_password
from app.services import auth

PASSWORD = "Secret123"
OFFICE_IP = {"X-Real-IP": "10.0.0.1"}


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False, autoflush=False)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    sent = []
    monkeypatch.setattr(auth, "send_email", lambda to, subject, text: sent.append((to, subject, text)))
    monkeypatch.setattr(auth, "settings", replace(auth.settings, allowed_email_domains=("corp.ru",), email_code_resend_seconds=0))
    auth.reset_memory_limits()
    main.app.dependency_overrides[get_db] = override_db
    client = TestClient(main.app)
    yield type("Env", (), {"client": client, "sent": sent, "Session": Session})
    main.app.dependency_overrides.clear()
    auth.reset_memory_limits()


def last_code(env):
    return re.search(r"Ваш код: (\d{6})", env.sent[-1][2]).group(1)


def add_user(env, email="anna@corp.ru", password=PASSWORD):
    with env.Session() as db:
        db.add(User(email=email, full_name="Анна", password_hash=hash_password(password)))
        db.commit()


def login(env, email="anna@corp.ru", password=PASSWORD, headers=OFFICE_IP):
    return env.client.post("/api/auth/login", json={"email": email, "password": password}, headers=headers)


def register(env, email="new@corp.ru", password=PASSWORD):
    env.client.post("/api/auth/register/request-code", json={"email": email})
    return env.client.post("/api/auth/register", json={"email": email, "code": last_code(env),
                                                       "department": "игсу", "phone": "+7 999 123-45-67", "full_name": "Новый С. И.", "password": password})


# --- Registration ---------------------------------------------------------------

def test_registration_requires_code_sent_to_corporate_mail(env):
    response = env.client.post("/api/auth/register/request-code", json={"email": "New@Corp.ru"})
    assert response.status_code == 200
    assert env.sent[-1][0] == "new@corp.ru"
    code = last_code(env)
    response = env.client.post("/api/auth/register", json={"email": "new@corp.ru", "code": code,
                                                           "department": "игсу", "phone": "+7 999 123-45-67", "full_name": "Новый С. И.", "password": PASSWORD})
    assert response.status_code == 201
    assert response.json()["user"]["email"] == "new@corp.ru"
    assert env.client.get("/api/auth/me").status_code == 200
    with env.Session() as db:
        assert db.scalar(select(User).where(User.email == "new@corp.ru")).email_verified_at is not None


def test_foreign_domain_is_rejected(env):
    response = env.client.post("/api/auth/register/request-code", json={"email": "someone@gmail.com"})
    assert response.status_code == 403
    assert not env.sent


def test_registration_without_valid_code_fails(env):
    env.client.post("/api/auth/register/request-code", json={"email": "new@corp.ru"})
    wrong = "000000" if last_code(env) != "000000" else "111111"
    response = env.client.post("/api/auth/register", json={"email": "new@corp.ru", "code": wrong,
                                                           "department": "игсу", "phone": "+7 999 123-45-67", "full_name": "Новый С. И.", "password": PASSWORD})
    assert response.status_code == 400
    assert "Осталось попыток: 4" in response.json()["detail"]


def test_code_is_burned_after_too_many_wrong_attempts(env):
    env.client.post("/api/auth/register/request-code", json={"email": "new@corp.ru"})
    code = last_code(env)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        env.client.post("/api/auth/register", json={"email": "new@corp.ru", "code": wrong, "department": "игсу", "phone": "+7 999 123-45-67", "full_name": "Новый С. И.", "password": PASSWORD})
    response = env.client.post("/api/auth/register", json={"email": "new@corp.ru", "code": code, "department": "игсу", "phone": "+7 999 123-45-67", "full_name": "Новый С. И.", "password": PASSWORD})
    assert response.status_code == 400


def test_only_newest_code_is_valid_and_code_is_single_use(env):
    env.client.post("/api/auth/register/request-code", json={"email": "new@corp.ru"})
    first = last_code(env)
    env.client.post("/api/auth/register/request-code", json={"email": "new@corp.ru"})
    second = last_code(env)
    if first != second:
        body = {"email": "new@corp.ru", "code": first, "department": "игсу", "phone": "+7 999 123-45-67", "full_name": "Новый С. И.", "password": PASSWORD}
        assert env.client.post("/api/auth/register", json=body).status_code == 400
    body = {"email": "new@corp.ru", "code": second, "department": "игсу", "phone": "+7 999 123-45-67", "full_name": "Новый С. И.", "password": PASSWORD}
    assert env.client.post("/api/auth/register", json=body).status_code == 201
    assert env.client.post("/api/auth/register", json=body).status_code == 409


def test_expired_code_is_rejected(env):
    env.client.post("/api/auth/register/request-code", json={"email": "new@corp.ru"})
    with env.Session() as db:
        item = db.scalar(select(EmailCode))
        item.expires_at = item.created_at - timedelta(minutes=1)
        db.commit()
    body = {"email": "new@corp.ru", "code": last_code(env), "department": "игсу", "phone": "+7 999 123-45-67", "full_name": "Новый С. И.", "password": PASSWORD}
    assert env.client.post("/api/auth/register", json=body).status_code == 400


def test_registered_address_cannot_request_registration_code(env):
    add_user(env)
    assert env.client.post("/api/auth/register/request-code", json={"email": "anna@corp.ru"}).status_code == 409
    assert not env.sent


def test_weak_password_is_rejected(env):
    response = register(env, password="password")
    assert response.status_code == 422
    assert "цифру" in response.json()["detail"]


def test_resend_cooldown_and_hourly_limit(env, monkeypatch):
    monkeypatch.setattr(auth, "settings", replace(auth.settings, email_code_resend_seconds=60))
    assert env.client.post("/api/auth/register/request-code", json={"email": "new@corp.ru"}).status_code == 200
    assert env.client.post("/api/auth/register/request-code", json={"email": "new@corp.ru"}).status_code == 429
    monkeypatch.setattr(auth, "settings", replace(auth.settings, email_code_resend_seconds=0, email_code_max_per_hour=2))
    assert env.client.post("/api/auth/register/request-code", json={"email": "new@corp.ru"}).status_code == 200
    assert env.client.post("/api/auth/register/request-code", json={"email": "new@corp.ru"}).status_code == 429


def test_failed_delivery_returns_503_and_keeps_no_code(env, monkeypatch):
    def broken(*_):
        raise auth.EmailDeliveryError("smtp down")
    monkeypatch.setattr(auth, "send_email", broken)
    assert env.client.post("/api/auth/register/request-code", json={"email": "new@corp.ru"}).status_code == 503
    with env.Session() as db:
        assert db.scalar(select(EmailCode)) is None


# --- Password reset and change -------------------------------------------------------

def test_forgot_password_does_not_reveal_unknown_address(env):
    response = env.client.post("/api/auth/password/forgot", json={"email": "ghost@corp.ru"})
    assert response.status_code == 200
    assert not env.sent


def test_password_reset_with_code_signs_in_and_kills_old_sessions(env):
    add_user(env)
    old = TestClient(main.app)
    assert login(env).status_code == 200
    old.cookies.update(env.client.cookies)
    env.client.cookies.clear()
    assert env.client.post("/api/auth/password/forgot", json={"email": "anna@corp.ru"}).status_code == 200
    response = env.client.post("/api/auth/password/reset", json={"email": "anna@corp.ru", "code": last_code(env), "password": "NewSecret456"})
    assert response.status_code == 200
    assert env.client.get("/api/auth/me").status_code == 200
    assert old.get("/api/auth/me").status_code == 401
    assert login(env, password=PASSWORD).status_code == 401
    assert login(env, password="NewSecret456").status_code == 200


def test_password_reset_lifts_login_lock(env):
    add_user(env)
    for _ in range(6):
        login(env, password="wrong-pass1")
    assert login(env).status_code == 429
    env.client.post("/api/auth/password/forgot", json={"email": "anna@corp.ru"})
    env.client.post("/api/auth/password/reset", json={"email": "anna@corp.ru", "code": last_code(env), "password": "NewSecret456"})
    env.client.cookies.clear()
    assert login(env, password="NewSecret456").status_code == 200


def test_change_password_requires_current_one_and_keeps_this_session(env):
    add_user(env)
    data = login(env).json()
    headers = {"X-CSRF-Token": data["csrf_token"]}
    bad = env.client.post("/api/auth/password/change", json={"current_password": "nope", "password": "NewSecret456"}, headers=headers)
    assert bad.status_code == 400
    ok = env.client.post("/api/auth/password/change", json={"current_password": PASSWORD, "password": "NewSecret456"}, headers=headers)
    assert ok.status_code == 200
    assert env.client.get("/api/auth/me").json()["csrf_token"] == ok.json()["csrf_token"]
    env.client.cookies.clear()
    assert login(env, password="NewSecret456").status_code == 200


def test_change_password_needs_csrf(env):
    add_user(env)
    login(env)
    response = env.client.post("/api/auth/password/change", json={"current_password": PASSWORD, "password": "NewSecret456"})
    assert response.status_code == 403


# --- Brute-force protection -------------------------------------------------------

def test_wrong_passwords_pause_only_that_account(env):
    add_user(env, "anna@corp.ru")
    add_user(env, "boris@corp.ru")
    for _ in range(4):
        assert login(env, password="wrong-pass1").status_code == 401
    assert login(env, password="wrong-pass1").status_code == 401  # 5th failure starts the pause
    response = login(env)
    assert response.status_code == 429
    assert "восстановите пароль" in response.json()["detail"]
    # A colleague behind the same office IP is not affected.
    assert login(env, "boris@corp.ru").status_code == 200


def test_many_colleagues_mistyping_from_one_ip_are_not_blocked(env):
    for index in range(40):
        add_user(env, f"user{index}@corp.ru")
    for index in range(40):
        assert login(env, f"user{index}@corp.ru", password="typo-pass1").status_code == 401
        assert login(env, f"user{index}@corp.ru", password="typo-pass2").status_code == 401
    for index in range(40):
        assert login(env, f"user{index}@corp.ru").status_code == 200


def test_successful_login_resets_failure_counter(env):
    add_user(env)
    for _ in range(4):
        login(env, password="wrong-pass1")
    assert login(env).status_code == 200
    for _ in range(4):
        assert login(env, password="wrong-pass1").status_code == 401
    assert login(env).status_code == 200


def test_pause_expires(env):
    add_user(env)
    for _ in range(5):
        login(env, password="wrong-pass1")
    assert login(env).status_code == 429
    with env.Session() as db:
        user = db.scalar(select(User))
        user.locked_until = auth.utcnow() - timedelta(seconds=1)
        db.commit()
    assert login(env).status_code == 200


def test_unknown_email_behaves_like_existing_one(env):
    for _ in range(5):
        assert login(env, "ghost@corp.ru", password="wrong-pass1").status_code == 401
    assert login(env, "ghost@corp.ru", password="wrong-pass1").status_code == 429


def test_ip_limit_is_a_high_safety_net_and_can_be_disabled(env, monkeypatch):
    monkeypatch.setattr(auth, "settings", replace(auth.settings, ip_max_failures=3))
    for index in range(3):
        login(env, f"x{index}@corp.ru", password="wrong-pass1")
    assert login(env, "y@corp.ru", password="wrong-pass1").status_code == 429
    assert login(env, "y@corp.ru", password="wrong-pass1", headers={"X-Real-IP": "10.0.0.2"}).status_code == 401
    monkeypatch.setattr(auth, "settings", replace(auth.settings, ip_max_failures=0))
    assert login(env, "y@corp.ru", password="wrong-pass1").status_code == 401


def test_lock_grows_and_is_capped():
    s = auth.settings
    assert [auth._lock_minutes(n) for n in range(s.login_max_failures - 1, s.login_max_failures + 6)] == [0, 1, 2, 4, 8, 15, 15]
