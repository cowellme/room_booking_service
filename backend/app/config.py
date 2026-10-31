import os
from dataclasses import dataclass
from pathlib import Path


def load_local_environment() -> None:
    """Load persistent local settings without overriding real environment variables."""
    backend_dir = Path(__file__).resolve().parents[1]
    for path in (backend_dir / ".env", backend_dir.parent / ".env"):
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if value[:1] == value[-1:] and value[:1] in {'"', "'"}:
                value = value[1:-1]
            os.environ.setdefault(key, value)
        break


load_local_environment()


@dataclass(frozen=True)
class Settings:
    database_url: str
    secret_key: str
    cookie_secure: bool
    allowed_origins: tuple[str, ...]
    seed_demo_data: bool
    work_hours_start: int = 8
    work_hours_end: int = 22
    slot_minutes: int = 30
    min_booking_minutes: int = 30
    max_booking_minutes: int = 840
    # How far ahead a booking may be made; protects against typos such as 2062 instead of 2026.
    max_days_ahead: int = 730
    timezone: str = "Europe/Moscow"
    allowed_email_domains: tuple[str, ...] = ()
    lifecycle_worker_enabled: bool = True
    lifecycle_interval_seconds: int = 30
    # Email delivery: "log" prints codes to the server log, "smtp" sends real mail.
    email_mode: str = "log"
    smtp_host: str = "smtp.yandex.ru"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_security: str = "ssl"
    smtp_timeout_seconds: int = 15
    app_public_url: str = ""
    email_code_ttl_minutes: int = 15
    email_code_max_attempts: int = 5
    email_code_resend_seconds: int = 60
    email_code_max_per_hour: int = 6
    # Brute-force protection works per account; the per-IP limit is only a
    # coarse safety net because the whole office shares one external address.
    login_max_failures: int = 5
    login_lock_minutes: int = 1
    login_lock_max_minutes: int = 15
    login_failure_window_minutes: int = 30
    ip_max_failures: int = 300
    ip_max_codes_per_hour: int = 300


def _int(name: str, default: int, low: int, high: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not low <= value <= high:
        raise RuntimeError(f"{name} must be between {low} and {high}")
    return value


def get_settings() -> Settings:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    secret_key = os.getenv("SECRET_KEY")
    if not secret_key or len(secret_key) < 32:
        raise RuntimeError("SECRET_KEY with at least 32 characters is required")
    smtp_host = os.getenv("SMTP_HOST", "smtp.yandex.ru").strip()
    smtp_user = os.getenv("SMTP_USER", "").strip()
    email_mode = os.getenv("EMAIL_MODE", "").strip().lower() or ("smtp" if smtp_user else "log")
    if email_mode not in {"log", "smtp"}:
        raise RuntimeError("EMAIL_MODE must be 'log' or 'smtp'")
    if email_mode == "smtp" and not (smtp_host and smtp_user and os.getenv("SMTP_PASSWORD")):
        raise RuntimeError("EMAIL_MODE=smtp requires SMTP_HOST, SMTP_USER and SMTP_PASSWORD")
    smtp_security = os.getenv("SMTP_SECURITY", "ssl").strip().lower()
    if smtp_security not in {"ssl", "starttls", "none"}:
        raise RuntimeError("SMTP_SECURITY must be 'ssl', 'starttls' or 'none'")
    lifecycle_interval = int(os.getenv("LIFECYCLE_INTERVAL_SECONDS", "30"))
    if not 1 <= lifecycle_interval <= 3600:
        raise RuntimeError("LIFECYCLE_INTERVAL_SECONDS must be between 1 and 3600")
    return Settings(
        database_url=database_url,
        lifecycle_worker_enabled=os.getenv("LIFECYCLE_WORKER_ENABLED", "true").lower() == "true",
        lifecycle_interval_seconds=lifecycle_interval,
        secret_key=secret_key,
        cookie_secure=os.getenv("COOKIE_SECURE", "true").lower() == "true",
        allowed_origins=tuple(x.strip() for x in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if x.strip()),
        seed_demo_data=os.getenv("SEED_DEMO_DATA", "false").lower() == "true",
        work_hours_start=int(os.getenv("WORK_HOURS_START", "8")),
        work_hours_end=int(os.getenv("WORK_HOURS_END", "22")),
        slot_minutes=int(os.getenv("TIME_SLOT_MINUTES", "30")),
        min_booking_minutes=int(os.getenv("MIN_BOOKING_MINUTES", "30")),
        max_booking_minutes=int(os.getenv("MAX_BOOKING_MINUTES", "840")),
        max_days_ahead=_int("MAX_BOOKING_DAYS_AHEAD", 730, 1, 3650),
        timezone=os.getenv("APP_TIMEZONE", "Europe/Moscow"),
        allowed_email_domains=tuple(x.strip().lower().lstrip("@") for x in os.getenv("ALLOWED_EMAIL_DOMAINS", "").split(",") if x.strip()),
        email_mode=email_mode,
        smtp_host=smtp_host,
        smtp_port=_int("SMTP_PORT", 465, 1, 65535),
        smtp_user=smtp_user,
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", "").strip() or smtp_user,
        smtp_security=smtp_security,
        smtp_timeout_seconds=_int("SMTP_TIMEOUT_SECONDS", 15, 1, 120),
        app_public_url=os.getenv("APP_PUBLIC_URL", "").strip().rstrip("/"),
        email_code_ttl_minutes=_int("EMAIL_CODE_TTL_MINUTES", 15, 1, 1440),
        email_code_max_attempts=_int("EMAIL_CODE_MAX_ATTEMPTS", 5, 1, 50),
        email_code_resend_seconds=_int("EMAIL_CODE_RESEND_SECONDS", 60, 0, 3600),
        email_code_max_per_hour=_int("EMAIL_CODE_MAX_PER_HOUR", 6, 1, 1000),
        login_max_failures=_int("LOGIN_MAX_FAILURES", 5, 1, 1000),
        login_lock_minutes=_int("LOGIN_LOCK_MINUTES", 1, 0, 1440),
        login_lock_max_minutes=_int("LOGIN_LOCK_MAX_MINUTES", 15, 0, 1440),
        login_failure_window_minutes=_int("LOGIN_FAILURE_WINDOW_MINUTES", 30, 1, 1440),
        ip_max_failures=_int("LOGIN_IP_MAX_FAILURES", 300, 0, 1000000),
        ip_max_codes_per_hour=_int("EMAIL_IP_MAX_CODES_PER_HOUR", 300, 0, 1000000),
    )


settings = get_settings()
