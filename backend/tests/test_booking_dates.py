from datetime import time, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app import main
from app.config import settings
from app.models import Booking
from app.schemas import AvailabilityRequest, BatchBookingCreate, BookingCreate, PhoneBookingCreate
from app.services import booking_lifecycle
from app.services.availability import build_availability
from test_booking_logistics import form
from test_request_flow import DAY, env, request


def date_only_form(env):
    data = form(env)
    data.pop("time_start")
    data.pop("time_end")
    return data


def test_one_day_uses_configured_work_hours(env):
    data = date_only_form(env)
    entry = main.create_booking(BookingCreate(**data, date_end=DAY), env.anna, env.db)
    assert entry["date"] == DAY.isoformat() and entry["series_id"] is None
    assert env.db.get(Booking, entry["id"]).time_start == time(settings.work_hours_start)
    assert env.db.get(Booking, entry["id"]).time_end == time(settings.work_hours_end)


@pytest.mark.parametrize("role", ["anna", "admin"])
def test_inclusive_period_saves_the_room_set_per_day(env, role):
    data = date_only_form(env)
    data.update(date_end=DAY + timedelta(days=2),
                extra_rooms=[{"room_id": env.rooms[1].id, "purpose": "Штаб"}])
    if role == "admin":
        result = main.create_phone_booking(PhoneBookingCreate(**data), env.admin, env.db)
    else:
        result = main.create_booking(BookingCreate(**data), env.anna, env.db)
    entries = list(env.db.scalars(select(Booking).where(Booking.series_id == result["series_id"])))
    assert len(entries) == 6
    assert {entry.date for entry in entries} == {DAY + timedelta(days=d) for d in range(3)}
    assert {entry.status for entry in entries} == ({"approved"} if role == "admin" else {"pending"})
    assert sum(entry.parent_booking_id is not None for entry in entries) == 3
    assert all(entry.time_start == time(settings.work_hours_start) and
               entry.time_end == time(settings.work_hours_end) for entry in entries)
    if role != "admin":
        booking_lifecycle.transition_series_status(env.db, result["series_id"], env.admin, "approved")
        assert all(entry.status == "approved" for entry in entries)


def test_conflict_on_later_date_is_found_and_period_rolls_back(env):
    later = DAY + timedelta(days=1)
    existing = request(env, env.admin, day=later, room=1, start="14:00", end="15:00")
    result = build_availability(env.db, AvailabilityRequest(date=DAY, date_end=later))
    assert result["occupied"][0]["conflict"]["date"] == later.isoformat()
    data = date_only_form(env)
    data.update(date_end=later, extra_rooms=[{"room_id": env.rooms[1].id, "purpose": "Штаб"}])
    with pytest.raises(HTTPException) as error:
        main.create_booking(BookingCreate(**data), env.anna, env.db)
    assert error.value.status_code == 409 and f"{later:%d.%m.%Y}" in error.value.detail
    assert list(env.db.scalars(select(Booking.id))) == [existing.id]


def test_conflict_rejects_the_whole_kit_on_only_one_day(env):
    later = DAY + timedelta(days=1)
    data = date_only_form(env)
    data.update(date_end=later, extra_rooms=[{"room_id": env.rooms[1].id, "purpose": "Штаб"}])
    result = main.create_booking(BookingCreate(**data), env.anna, env.db)
    request(env, env.admin, day=later, room=1, start="14:00", end="15:00")
    entries = list(env.db.scalars(select(Booking).where(Booking.series_id == result["series_id"])))
    assert len(entries) == 4
    assert all(entry.status == ("rejected" if entry.date == later else "pending") for entry in entries)


def test_series_preserves_weekday_selection_without_times(env):
    data = date_only_form(env)
    result = main.create_user_booking_series(
        BatchBookingCreate(**data, date_end=DAY + timedelta(days=7), room_ids=[env.rooms[0].id],
                           weekdays=[DAY.weekday()]), env.anna, env.db)
    entries = list(env.db.scalars(select(Booking).where(Booking.series_id == result["series_id"])))
    assert {entry.date for entry in entries} == {DAY, DAY + timedelta(days=7)}


def test_invalid_ranges_and_missing_time_half_rejected(env):
    data = date_only_form(env)
    with pytest.raises(ValidationError):
        BookingCreate(**data, date_end=DAY - timedelta(days=1))
    with pytest.raises(ValidationError):
        BookingCreate(**data, time_start="10:00")
