from datetime import date, timedelta, time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.booking_lifecycle import (
    CLOSED_BOOKING_STATUSES,
    STATUS_SUMMARIES,
    delete_booking_record,
    ensure_booking_open,
    set_booking_archived,
)


@pytest.mark.parametrize("status", sorted(CLOSED_BOOKING_STATUSES))
def test_closed_booking_cannot_be_changed(status):
    with pytest.raises(HTTPException) as exc:
        ensure_booking_open(SimpleNamespace(status=status))
    assert exc.value.status_code == 409


@pytest.mark.parametrize("status", ["pending", "approved"])
def test_active_booking_can_be_changed(status):
    ensure_booking_open(SimpleNamespace(status=status))


def test_every_allowed_admin_transition_has_audit_summary():
    assert set(STATUS_SUMMARIES) == {"approved", "rejected", "completed", "no_show"}


def test_future_active_booking_cannot_be_archived():
    booking = SimpleNamespace(
        status="approved",
        date=date.today() + timedelta(days=1),
        time_end=time(12),
    )
    with pytest.raises(HTTPException) as exc:
        set_booking_archived(None, booking, SimpleNamespace(id=1), True)
    assert exc.value.status_code == 409


def test_booking_with_transfer_child_cannot_be_deleted():
    db = SimpleNamespace(scalar=lambda _statement: 123)
    with pytest.raises(HTTPException) as exc:
        delete_booking_record(db, SimpleNamespace(id=10))
    assert exc.value.status_code == 409


def test_standalone_booking_is_deleted_and_committed():
    calls = []
    db = SimpleNamespace(
        scalar=lambda _statement: None,
        delete=lambda booking: calls.append(("delete", booking.id)),
        commit=lambda: calls.append(("commit", None)),
    )
    delete_booking_record(db, SimpleNamespace(id=10))
    assert calls == [("delete", 10), ("commit", None)]
