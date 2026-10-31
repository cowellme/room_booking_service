"""Local wall-clock time of the institution, independent of the server time zone."""
from datetime import date, datetime, timedelta, timezone

from .config import settings

try:
    from zoneinfo import ZoneInfo
    _ZONE = ZoneInfo(settings.timezone)
except Exception:  # tzdata is missing or the name is unknown: fall back to Moscow time
    _ZONE = timezone(timedelta(hours=3))


def local_now() -> datetime:
    return datetime.now(_ZONE).replace(tzinfo=None)


def local_today() -> date:
    return local_now().date()


def utc_now() -> datetime:
    """Aware UTC timestamp for timestamptz columns.

    A naive datetime.utcnow() is read by PostgreSQL in the session time zone, so on
    a server set to Moscow time every stored moment would shift by three hours.
    """
    return datetime.now(timezone.utc)
