"""Russian five-day working calendar (official transfers for 2026 and 2027).

Sources: Government decrees 24.09.2025 No.1466 and 17.09.2026 No.1187.
Other years use statutory holidays only; publish transfers before using them.
"""
from datetime import date, datetime, time, timedelta, timezone
from ..timeutils import _ZONE

TRANSFERS = {
    2026: {date(2026, 1, 9), date(2026, 12, 31)},
    2027: {date(2027, 2, 22), date(2027, 11, 5), date(2027, 12, 31)},
}
WORKING_WEEKENDS = {date(2027, 2, 20)}

def is_working_day(day: date) -> bool:
    if day in WORKING_WEEKENDS:
        return True
    holidays = {date(day.year, 1, n) for n in range(1, 9)}
    fixed = {(2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4)}
    holidays.update(date(day.year, month, number) for month, number in fixed)
    # Article 112: non-January holidays falling on weekends move to Monday.
    for month, number in fixed:
        holiday = date(day.year, month, number)
        if holiday.weekday() >= 5:
            holidays.add(holiday + timedelta(days=7 - holiday.weekday()))
    return day.weekday() < 5 and day not in holidays and day not in TRANSFERS.get(day.year, set())

def add_working_days(start: date, count: int = 7) -> date:
    while count > 0:
        start += timedelta(days=1)
        if is_working_day(start):
            count -= 1
    return start

def review_deadline(created: datetime) -> datetime:
    # Timestamp columns are UTC; SQLite returns them without tzinfo in tests.
    local = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created
    local = local.astimezone(_ZONE)
    return datetime.combine(add_working_days(local.date()), local.timetz())

def review_info(created: datetime | None, now: datetime) -> dict:
    if created is None:
        return {}
    deadline = review_deadline(created)
    current = now.replace(tzinfo=_ZONE) if now.tzinfo is None else now.astimezone(_ZONE)
    remaining = 0
    day = current.date()
    while day < deadline.date():
        day += timedelta(days=1)
        remaining += int(is_working_day(day))
    if current < deadline and remaining == 0:
        remaining = 1
    return {"review_deadline": deadline.isoformat(), "review_days_left": remaining,
            "review_overdue": current >= deadline, "review_urgent": remaining <= 2}
