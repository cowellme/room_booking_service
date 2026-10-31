"""Completing an event must never release an ongoing approved interval."""
from datetime import datetime, time, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app import main
from app.models import Booking, BookingEvent
from app.schemas import AvailabilityRequest
from app.services import booking_lifecycle as lifecycle, bookings
from app.services.availability import build_availability
from test_booking_concurrency import race, payload, DAY


def approved(race, db):
    return bookings.create_booking(db, payload(race), race.admin)


@pytest.mark.parametrize('now', [
    datetime(2030, 1, 13, 23, 59), datetime(2030, 1, 14, 9, 59, 59),
    datetime(2030, 1, 14, 10), datetime(2030, 1, 14, 10, 30),
    datetime(2030, 1, 14, 11, 59, 59, 999999),
])
def test_early_completion_does_not_change_status_or_history(race, now):
    with race.factory() as db:
        item = approved(race, db)
        item_id = item.id
        before = db.scalar(select(func.count()).select_from(BookingEvent).where(BookingEvent.booking_id == item.id))
        race.clock.now = now
        with pytest.raises(HTTPException) as caught:
            lifecycle.transition_booking_status(db, item, race.admin, 'completed')
        assert caught.value.status_code == 409
        assert 'после планового окончания' in caught.value.detail
        assert item.status == 'approved'
        assert db.scalar(select(func.count()).select_from(BookingEvent).where(BookingEvent.booking_id == item.id)) == before
    with race.factory() as check:
        assert check.get(Booking, item_id).status == 'approved'


@pytest.mark.parametrize('now', [datetime(2030, 1, 14, 12), datetime(2030, 1, 14, 12, 0, 1), datetime(2030, 1, 15, 0)])
def test_completion_is_allowed_at_or_after_scheduled_end(race, now):
    with race.factory() as db:
        item = approved(race, db)
        race.clock.now = now
        lifecycle.transition_booking_status(db, item, race.admin, 'completed')
        assert item.status == 'completed'
        assert db.scalar(select(func.count()).select_from(BookingEvent).where(
            BookingEvent.booking_id == item.id, BookingEvent.event_type == 'completed')) == 1


def test_failed_early_completion_keeps_availability_and_both_calendars_correct(race):
    with race.factory() as db:
        item = approved(race, db)
        race.clock.now = datetime(2030, 1, 14, 10, 30)
        with pytest.raises(HTTPException):
            lifecycle.transition_booking_status(db, item, race.admin, 'completed')
        conflict = bookings.find_conflict(db, item.room_id, DAY, time(11), time(12))
        assert conflict.id == item.id
        for actor in (race.admin, race.user):
            calendar = main.bookings(DAY, DAY, user=actor, db=db)
            assert any(row['id'] == item.id and row['status'] == 'approved' for row in calendar)
        availability = build_availability(db, AvailabilityRequest(date=DAY, time_start='11:00', time_end='12:00', participants=1))
        assert any(room['id'] == item.room_id for room in availability['occupied'])
        assert all(room['id'] != item.room_id for room in availability['free'])
        data = payload(race).model_dump(); data.update(time_start='11:00', time_end='12:00')
        from app.schemas import BookingCreate
        with pytest.raises(HTTPException) as caught:
            bookings.create_booking(db, BookingCreate(**data), race.user)
        # Same-day creation is now rejected by the seven-working-day rule first.
        # The find_conflict/availability assertions above still verify occupancy.
        assert caught.value.status_code == 400
        assert '7 рабочих дней' in caught.value.detail


def test_no_show_can_still_be_recorded_after_start_but_not_completed_early(race):
    with race.factory() as db:
        item = approved(race, db)
        race.clock.now = datetime(2030, 1, 14, 10, 30)
        lifecycle.transition_booking_status(db, item, race.admin, 'no_show')
        assert item.status == 'no_show'
        with pytest.raises(HTTPException) as caught:
            lifecycle.transition_booking_status(db, item, race.admin, 'completed')
        assert caught.value.status_code == 409 and item.status == 'no_show'
        race.clock.now = datetime(2030, 1, 14, 12)
        lifecycle.transition_booking_status(db, item, race.admin, 'completed')
        assert item.status == 'completed'


def test_no_show_before_start_remains_forbidden(race):
    with race.factory() as db:
        item = approved(race, db)
        with pytest.raises(HTTPException) as caught:
            lifecycle.transition_booking_status(db, item, race.admin, 'no_show')
        assert caught.value.status_code == 409 and item.status == 'approved'


def test_automatic_completion_still_waits_until_end_and_retains_calendar_history(race):
    with race.factory() as db:
        item = approved(race, db)
        race.clock.now = datetime(2030, 1, 14, 11, 59, 59)
        lifecycle.expire_pending_requests(db)
        assert item.status == 'approved'
        race.clock.now = datetime(2030, 1, 14, 12)
        lifecycle.expire_pending_requests(db)
        assert item.status == 'completed'
        lifecycle.expire_pending_requests(db)
        assert db.scalar(select(func.count()).select_from(BookingEvent).where(
            BookingEvent.booking_id == item.id, BookingEvent.event_type == 'completed')) == 1
        for actor in (race.admin, race.user):
            assert any(row['id'] == item.id and row['status'] == 'completed'
                       for row in main.bookings(DAY, DAY, user=actor, db=db))
