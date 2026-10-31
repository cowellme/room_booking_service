"""Email confirmation codes, password rules and brute-force protection.

Employees work from one office network, so they all share one external IP.
Failed logins are therefore counted per account (email): after
LOGIN_MAX_FAILURES wrong passwords only that account waits a short, growing
pause, and a password reset by email lifts it at once. The per-IP counter is a
coarse safety net with a high limit (0 turns it off).
"""
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import math
import re
import secrets
import threading

from fastapi import HTTPException, Request
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..models import EmailCode, User
from .mailer import EmailDeliveryError, send_email

PURPOSE_REGISTER = "register"
PURPOSE_RESET = "reset"
CODE_SUBJECTS = {PURPOSE_REGISTER: "Код подтверждения регистрации", PURPOSE_RESET: "Код для сброса пароля"}
CODE_INTROS = {PURPOSE_REGISTER: "Вы регистрируетесь в сервисе бронирования аудиторий.",
               PURPOSE_RESET: "Кто-то запросил сброс пароля для вашей учётной записи в сервисе бронирования аудиторий."}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    # PostgreSQL returns aware values, SQLite (tests) returns naive UTC.
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def ensure_corporate_email(email: str) -> None:
    if settings.allowed_email_domains and email.rsplit("@", 1)[-1] not in settings.allowed_email_domains:
        domains = ", ".join(f"@{item}" for item in settings.allowed_email_domains)
        raise HTTPException(403, f"Регистрация доступна только с корпоративной почты ({domains})")


def client_ip(request: Request) -> str:
    # nginx passes the real address in X-Real-IP; without nginx use the socket address.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


def minutes_word(value: int) -> str:
    if value % 10 == 1 and value % 100 != 11:
        return "минуту"
    if value % 10 in (2, 3, 4) and value % 100 not in (12, 13, 14):
        return "минуты"
    return "минут"


class SlidingCounter:
    """In-memory event counter over a sliding window, per key."""

    def __init__(self, window: timedelta):
        self.window = window
        self.events: dict[str, deque[datetime]] = defaultdict(deque)
        self.lock = threading.Lock()

    def _trim(self, key: str, now: datetime) -> deque[datetime]:
        events = self.events[key]
        while events and events[0] <= now - self.window:
            events.popleft()
        if not events:
            self.events.pop(key, None)
            return deque()
        return events

    def count(self, key: str, now: datetime | None = None) -> int:
        with self.lock:
            return len(self._trim(key, now or utcnow()))

    def recent(self, key: str, now: datetime | None = None) -> list[datetime]:
        with self.lock:
            return list(self._trim(key, now or utcnow()))

    def hit(self, key: str, now: datetime | None = None) -> None:
        now = now or utcnow()
        with self.lock:
            self._trim(key, now)
            self.events[key].append(now)

    def clear(self) -> None:
        with self.lock:
            self.events.clear()


ip_failures = SlidingCounter(timedelta(minutes=15))
ip_codes = SlidingCounter(timedelta(hours=1))
# Failed logins for emails that have no account, so the answer looks the same.
unknown_email_failures = SlidingCounter(timedelta(minutes=30))


def reset_memory_limits() -> None:
    for counter in (ip_failures, ip_codes, unknown_email_failures):
        counter.clear()


# --- Passwords --------------------------------------------------------------------

def password_problem(password: str, email: str | None = None) -> str | None:
    if len(password) < 8:
        return "Пароль должен содержать не менее 8 символов"
    if len(password) > 128:
        return "Пароль должен быть не длиннее 128 символов"
    if password != password.strip():
        return "Пароль не должен начинаться или заканчиваться пробелом"
    if not any(char.isalpha() for char in password) or not any(char.isdigit() for char in password):
        return "Пароль должен содержать хотя бы одну букву и одну цифру"
    if email and password.lower() in {email.lower(), email.split("@", 1)[0].lower()}:
        return "Пароль не должен совпадать с адресом почты"
    return None


def ensure_password(password: str, email: str | None = None) -> None:
    if problem := password_problem(password, email):
        raise HTTPException(422, problem)


# --- Login protection -------------------------------------------------------------

def _lock_minutes(failures: int) -> int:
    """1, 2, 4, 8... minutes for each failure past the limit, capped."""
    over = failures - settings.login_max_failures
    if over < 0 or settings.login_lock_minutes == 0:
        return 0
    return min(settings.login_lock_max_minutes, settings.login_lock_minutes * 2 ** min(over, 16))


def _locked_message(until: datetime, now: datetime) -> str:
    minutes = max(1, math.ceil((until - now).total_seconds() / 60))
    return (f"Слишком много неверных попыток входа. Повторите через {minutes} {minutes_word(minutes)} "
            "или восстановите пароль по почте")


def ensure_ip_allowed(ip: str) -> None:
    if settings.ip_max_failures and ip_failures.count(ip) >= settings.ip_max_failures:
        raise HTTPException(429, "С вашей сети слишком много неудачных попыток входа. Повторите через несколько минут")


def ensure_account_unlocked(user: User | None, email: str, now: datetime | None = None) -> None:
    now = now or utcnow()
    if user is not None:
        until = as_utc(user.locked_until)
        if until and until > now:
            raise HTTPException(429, _locked_message(until, now))
        return
    failures = unknown_email_failures.recent(email, now)
    if failures and len(failures) >= settings.login_max_failures:
        until = failures[-1] + timedelta(minutes=_lock_minutes(len(failures)))
        if until > now:
            raise HTTPException(429, _locked_message(until, now))


def record_login_failure(db: Session, user: User | None, email: str, ip: str, now: datetime | None = None) -> None:
    now = now or utcnow()
    ip_failures.hit(ip, now)
    if user is None:
        unknown_email_failures.hit(email, now)
        return
    last = as_utc(user.last_failed_login_at)
    window = timedelta(minutes=settings.login_failure_window_minutes)
    failures = 1 if not last or now - last > window else (user.failed_login_count or 0) + 1
    user.failed_login_count = failures
    user.last_failed_login_at = now
    if minutes := _lock_minutes(failures):
        user.locked_until = now + timedelta(minutes=minutes)
    db.commit()


def clear_login_failures(user: User) -> None:
    user.failed_login_count = 0
    user.last_failed_login_at = None
    user.locked_until = None


# --- Email codes ------------------------------------------------------------------

def _code_hash(email: str, purpose: str, code: str) -> str:
    message = f"{purpose}:{email}:{code}".encode()
    return hmac.new(settings.secret_key.encode(), message, hashlib.sha256).hexdigest()


def issue_code(db: Session, email: str, purpose: str, ip: str, now: datetime | None = None) -> None:
    now = now or utcnow()
    if settings.ip_max_codes_per_hour and ip_codes.count(ip, now) >= settings.ip_max_codes_per_hour:
        raise HTTPException(429, "Слишком много запросов кода из вашей сети. Повторите позже")
    recent = list(db.scalars(select(EmailCode.created_at).where(
        EmailCode.email == email, EmailCode.purpose == purpose,
        EmailCode.created_at > now - timedelta(hours=1)).order_by(EmailCode.created_at.desc())))
    if recent:
        wait = settings.email_code_resend_seconds - (now - as_utc(recent[0])).total_seconds()
        if wait > 0:
            raise HTTPException(429, f"Новый код можно запросить через {math.ceil(wait)} с")
    if len(recent) >= settings.email_code_max_per_hour:
        raise HTTPException(429, "Слишком много запросов кода для этого адреса. Повторите через час")
    purge_old_codes(db, now)
    code = f"{secrets.randbelow(1_000_000):06d}"
    # Only the newest code is valid.
    db.execute(update(EmailCode).where(EmailCode.email == email, EmailCode.purpose == purpose,
                                       EmailCode.consumed_at.is_(None)).values(consumed_at=now))
    item = EmailCode(email=email, purpose=purpose, code_hash=_code_hash(email, purpose, code), attempts=0,
                     requested_ip=ip[:64], created_at=now,
                     expires_at=now + timedelta(minutes=settings.email_code_ttl_minutes))
    db.add(item)
    db.flush()
    ttl = settings.email_code_ttl_minutes
    lines = [CODE_INTROS[purpose], "", f"Ваш код: {code}", "",
             f"Код действует {ttl} {minutes_word(ttl)}. Никому его не сообщайте."]
    if settings.app_public_url:
        lines += ["", f"Сервис: {settings.app_public_url}"]
    lines += ["", "Если вы ничего не запрашивали, просто проигнорируйте это письмо."]
    try:
        send_email(email, CODE_SUBJECTS[purpose], "\n".join(lines))
    except EmailDeliveryError as exc:
        db.rollback()
        raise HTTPException(503, "Не удалось отправить письмо. Попробуйте позже или обратитесь к администратору") from exc
    ip_codes.hit(ip, now)
    db.commit()


def consume_code(db: Session, email: str, purpose: str, code: str, now: datetime | None = None) -> None:
    """Accept the newest unused code or raise 400. Commits the attempt counter."""
    now = now or utcnow()
    code = code.strip()
    if not re.fullmatch(r"\d{6}", code):
        raise HTTPException(400, "Код состоит из 6 цифр")
    item = db.scalar(select(EmailCode).where(EmailCode.email == email, EmailCode.purpose == purpose,
                                             EmailCode.consumed_at.is_(None))
                     .order_by(EmailCode.created_at.desc(), EmailCode.id.desc()).limit(1).with_for_update())
    if item is None or as_utc(item.expires_at) <= now:
        raise HTTPException(400, "Код устарел или не запрашивался. Запросите новый код")
    if not hmac.compare_digest(item.code_hash, _code_hash(email, purpose, code)):
        item.attempts += 1
        left = settings.email_code_max_attempts - item.attempts
        if left <= 0:
            item.consumed_at = now
            db.commit()
            raise HTTPException(400, "Код введён неверно слишком много раз. Запросите новый код")
        db.commit()
        raise HTTPException(400, f"Неверный код. Осталось попыток: {left}")
    item.consumed_at = now


def purge_old_codes(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    result = db.execute(EmailCode.__table__.delete().where(EmailCode.created_at < now - timedelta(days=2)))
    return result.rowcount or 0


def user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email))
