"""Recheck current booking conditions before a moderation decision is saved."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ..models import Booking, Room
from .bookings import check_capacity, validate_booking_window


def validate_approval_conditions(db: Session, bookings: list[Booking]) -> None:
    """Validate the whole decision before changing any status or adding audit rows.

    Call after booking-row and room/day locks have been acquired. Reload rooms
    even when the ORM cache contains an old capacity/activity. PostgreSQL SHARE
    locks keep those characteristics stable until commit while allowing other
    approvals to read the same rooms. NOWAIT avoids waiting on an administrator
    editing room characteristics. Additional rooms retain their own participant
    count (usually None); they do not inherit the main event's capacity needs.
    """
    if not bookings:
        return
    room_ids = sorted({item.room_id for item in bookings})
    try:
        with db.no_autoflush:
            rooms = {room.id: room for room in db.scalars(
                select(Room).where(Room.id.in_(room_ids)).order_by(Room.id)
                .with_for_update(read=True, of=Room, nowait=True)
                .execution_options(populate_existing=True)
            )}
    except OperationalError as exc:
        if getattr(exc.orig, "sqlstate", None) != "55P03":
            raise
        db.rollback()
        raise HTTPException(409, "Характеристики аудитории сейчас изменяются. Обновите данные и повторите подтверждение") from exc
    for booking in bookings:
        room = rooms.get(booking.room_id)
        label = f"ауд. {room.number if room else booking.room_id}, {booking.date.strftime('%d.%m.%Y')}"
        if room is None or not room.is_active:
            raise HTTPException(409, f"Подтверждение невозможно: {label} — аудитория недоступна для бронирования")
        try:
            validate_booking_window(booking.date, booking.time_start, booking.time_end)
            check_capacity(room, booking.participants)
        except HTTPException as exc:
            raise HTTPException(409, f"Подтверждение невозможно: {label} — {exc.detail}") from exc
