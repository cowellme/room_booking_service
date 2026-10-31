"""Lock and reload booking records before making lifecycle decisions.

Room/day advisory locks protect availability. Row locks protect the request
itself from concurrent edits/cancellations. NOWAIT avoids lock-order deadlocks
between a decision, a room set and automatic rejection of competing requests.
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ..models import Booking

CHANGED_MESSAGE = "Бронирование изменилось. Обновите данные и повторите действие"
BUSY_MESSAGE = "С этой заявкой уже выполняется другое действие. Обновите данные и повторите попытку"
DECISION_FIELDS = ("status", "room_id", "date", "time_start", "time_end", "parent_booking_id", "series_id", "participants")


def lock_booking_rows(db: Session, statement) -> list[Booking]:
    """Return current rows, not cached ORM objects, locked until commit/rollback."""
    try:
        with db.no_autoflush:
            return list(db.scalars(statement.with_for_update(of=Booking, nowait=True)
                                   .execution_options(populate_existing=True)))
    except OperationalError as exc:
        if getattr(exc.orig, "sqlstate", None) != "55P03":
            raise
        db.rollback()
        raise HTTPException(409, BUSY_MESSAGE) from exc


def lock_booking_record(db: Session, booking: Booking) -> Booking:
    """Protect the whole room set, including independent actions on an extra room.

    A moved/cancelled request must not be approved using an object read earlier
    in the HTTP request. Reject stale decisions rather than silently applying
    them to a different room or schedule.
    """
    before = tuple(getattr(booking, name) for name in DECISION_FIELDS)
    booking_id, root_id = booking.id, booking.parent_booking_id or booking.id
    roots = lock_booking_rows(db, select(Booking).where(Booking.id == root_id))
    if not roots:
        raise HTTPException(409, CHANGED_MESSAGE)
    children = lock_booking_rows(db, select(Booking).where(Booking.parent_booking_id == root_id).order_by(Booking.id))
    current = next((item for item in roots + children if item.id == booking_id), None)
    if current is None or tuple(getattr(current, name) for name in DECISION_FIELDS) != before:
        raise HTTPException(409, CHANGED_MESSAGE)
    return current
