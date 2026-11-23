from datetime import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .database import get_db
from .models import Booking, Room, User
from .schemas import RejectRequest
from .security import admin_user, current_user
from .serializers import booking_to_dict
from .services.attachments import add_attachments
from .services.booking_lifecycle import transition_booking_status
from .services.bookings import find_conflict, intervals_overlap


router = APIRouter()


@router.get("/api/admin/bookings")
def moderation(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(403, "Недостаточно прав")
    stmt = (
        select(Booking)
        .options(joinedload(Booking.room).joinedload(Room.building), joinedload(Booking.department))
        .where(Booking.status.in_(("pending", "in_progress")))
        .order_by(Booking.created_at)
    )
    result = []
    items = list(db.scalars(stmt))
    for item in items:
        data = booking_to_dict(item, include_admin_notice=True)
        conflict = find_conflict(db, item.room_id, item.date, item.time_start, item.time_end, item.id)
        data["has_conflict"] = conflict is not None
        if conflict:
            data["conflict"] = {
                "id": conflict.id,
                "title": conflict.title,
                "time_start": conflict.time_start.strftime("%H:%M"),
                "time_end": conflict.time_end.strftime("%H:%M"),
            }
        result.append(data)
    for data in result:
        data["competing_requests"] = sum(
            1
            for other in result
            if other["id"] != data["id"]
            and other["room_id"] == data["room_id"]
            and other["date"] == data["date"]
            and intervals_overlap(
                time.fromisoformat(data["time_start"]),
                time.fromisoformat(data["time_end"]),
                time.fromisoformat(other["time_start"]),
                time.fromisoformat(other["time_end"]),
            )
            and not (data["series_id"] and other["series_id"] == data["series_id"])
        )
    return add_attachments(db, items, result)


@router.post("/api/admin/bookings/{booking_id}/approve")
def approve(booking_id: int, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    item = db.get(Booking, booking_id)
    if not item or item.status not in {"pending", "in_progress"}:
        raise HTTPException(404, "Заявка не найдена")
    transition_booking_status(db, item, user, "approved")
    return {"ok": True}


@router.post("/api/admin/bookings/{booking_id}/reject")
def reject(
    booking_id: int,
    payload: RejectRequest,
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    item = db.get(Booking, booking_id)
    if not item or item.status not in {"pending", "in_progress"}:
        raise HTTPException(404, "Заявка не найдена")
    transition_booking_status(db, item, user, "rejected", payload.reason)
    return {"ok": True}
