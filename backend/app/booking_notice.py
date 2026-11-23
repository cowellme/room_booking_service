"""Advisory lead time for administrators; never a booking validation rule."""

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

from .timeutils import _ZONE


LEAD_WORKDAYS = 7
DAY = timedelta(days=1)
FEDERAL_HOLIDAYS = {(1, day) for day in range(1, 9)} | {
    (2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4),
}
# Five-day calendar: federal holidays plus substitute days and annual transfers.
# 2026: Government Resolution No. 1466; 2027: No. 1187.
DAYS_OFF = {
    date(2026, 1, 9), date(2026, 3, 9), date(2026, 5, 11), date(2026, 12, 31),
    date(2027, 2, 22), date(2027, 5, 3), date(2027, 5, 10), date(2027, 6, 14),
    date(2027, 11, 5), date(2027, 12, 31),
}
WORKING_WEEKENDS = {date(2027, 2, 20)}


def is_workday(day: date) -> bool:
    return day in WORKING_WEEKENDS or (
        day.weekday() < 5 and (day.month, day.day) not in FEDERAL_HOLIDAYS and day not in DAYS_OFF
    )


@lru_cache(maxsize=1024)
def lead_time_cutoff(submitted_on: date) -> date:
    """Start counting on the next day; the seventh workday itself is on time."""
    day = submitted_on
    remaining = LEAD_WORKDAYS
    while remaining:
        day += DAY
        remaining -= is_workday(day)
    return day


def is_short_notice(created_at: datetime | None, event_on: date) -> bool:
    if created_at is None:
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return event_on < lead_time_cutoff(created_at.astimezone(_ZONE).date())
