from datetime import date, datetime, timezone

import pytest

from app.booking_notice import is_short_notice, lead_time_cutoff


@pytest.mark.parametrize(("submitted_on", "cutoff"), [
    (date(2026, 11, 16), date(2026, 11, 25)),
    (date(2026, 10, 30), date(2026, 11, 11)),
    (date(2026, 12, 30), date(2027, 1, 19)),
    (date(2027, 2, 18), date(2027, 3, 2)),
])
def test_cutoff_excludes_days_off_and_includes_working_saturday(submitted_on, cutoff):
    assert lead_time_cutoff(submitted_on) == cutoff


def test_short_notice_uses_local_creation_date_and_allows_exact_boundary():
    # Late Monday in UTC is already Tuesday in Moscow.
    created = datetime(2026, 11, 16, 22, tzinfo=timezone.utc)
    assert is_short_notice(created, date(2026, 11, 16))
    assert is_short_notice(created, date(2026, 11, 17))
    assert is_short_notice(created, date(2026, 11, 25))
    assert not is_short_notice(created, date(2026, 11, 26))
    assert not is_short_notice(None, date(2026, 11, 17))


def test_short_notice_is_only_serialized_for_admin_and_not_for_blocks():
    from datetime import time
    from app.models import Booking, Building, Room
    from app.serializers import booking_to_dict, calendar_booking_to_dict

    room = Room(number="102", name="Аудитория", building=Building(name="Второй учебный корпус"))
    booking = Booking(
        room=room, date=date(2026, 11, 17), time_start=time(10), time_end=time(11),
        status="approved", record_kind="booking", title="Тестовая заявка",
        created_at=datetime(2026, 11, 16, 10, tzinfo=timezone.utc),
    )
    assert "short_notice" not in booking_to_dict(booking)
    assert "short_notice" not in calendar_booking_to_dict(booking)
    assert calendar_booking_to_dict(booking, include_private=True)["short_notice"] is True
    booking.record_kind = "maintenance"
    assert calendar_booking_to_dict(booking, include_private=True)["short_notice"] is False
