from datetime import date, datetime

import pytest
from fastapi import HTTPException

from app.services import bookings


@pytest.mark.parametrize(("start", "expected"), [
    (date(2026, 11, 2), date(2026, 11, 12)),
    (date(2026, 11, 6), date(2026, 11, 17)),
    (date(2026, 11, 7), date(2026, 11, 17)),
    (date(2026, 12, 31), date(2027, 1, 19)),
])
def test_seven_working_days_excludes_request_day_and_weekends(start, expected):
    assert bookings.earliest_booking_date(start) == expected


def test_validate_lead_time_accepts_boundary_and_rejects_earlier(monkeypatch):
    monkeypatch.setattr(bookings, "local_now", lambda: datetime(2026, 11, 2, 12, 0))
    bookings.validate_booking_lead_time(date(2026, 11, 12))
    bookings.validate_booking_lead_time(date(2026, 11, 12))
    with pytest.raises(HTTPException) as failure:
        bookings.validate_booking_lead_time(date(2026, 11, 10))
    assert failure.value.status_code == 400
    assert "7 рабочих дней" in failure.value.detail
    assert "12.11.2026" in failure.value.detail
