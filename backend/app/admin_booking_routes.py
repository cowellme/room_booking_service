from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, cast, or_, select, text
from sqlalchemy.orm import Session, joinedload, selectinload

from .booking_routes import _add_extra_rooms, require_booking_logistics
from .database import get_db
from .models import Booking, BookingComment, BookingEvent, BookingObserver, Department, Room, User
from .schemas import (
    BookingArchiveRequest,
    BookingBulkArchiveRequest,
    BookingBulkRequest,
    BookingCancelRequest,
    BookingCommentCreate,
    BookingCommentResolve,
    BookingObserversUpdate,
    BookingStatusRequest,
    BookingTransferRequest,
    BookingUpdate,
    ExtraRoomsAdd,
)
from .security import admin_read_user, admin_user, csrf_protected, current_user
from .serializers import booking_to_dict
from .services.attachments import add_attachments, remove_unused_files
from .services.booking_lifecycle import (
    CLOSED_BOOKING_STATUSES,
    cancel_booking_record,
    delete_booking_records,
    get_booking_or_404,
    set_booking_archived,
    set_bookings_archived,
    transition_booking_status,
)
from .services.booking_locks import lock_booking_record
from .services.bookings import (
    BLOCKING_STATUSES,
    capacity_limit,
    check_capacity,
    find_conflict,
    intervals_overlap,
    record_event,
    reject_competing_requests,
    validate_booking_window,
)
from .services.operations import transfer_booking
from .services.room_sets import extra_rooms_of, move_extra_rooms
from .timeutils import utc_now


router = APIRouter()


@router.post("/api/admin/booking-center/{booking_id}/extra-rooms", status_code=201)
def add_admin_extra_rooms(
    booking_id: int,
    payload: ExtraRoomsAdd,
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    return _add_extra_rooms(db, get_booking_or_404(db, booking_id), payload, user, None)


@router.get("/api/admin/booking-center")
def booking_center(scope: str = "all", user: User = Depends(admin_read_user), db: Session = Depends(get_db)):
    stmt = select(Booking).options(
        joinedload(Booking.room).joinedload(Room.building),
        joinedload(Booking.owner),
        joinedload(Booking.cancelled_by),
        joinedload(Booking.archived_by),
        joinedload(Booking.department),
        joinedload(Booking.decided_by),
    )
    if scope == "mine":
        stmt = stmt.where(Booking.owner_id == user.id)
    elif scope != "all":
        raise HTTPException(400, "Неизвестная область просмотра")
    items = list(db.scalars(stmt.order_by(Booking.date.desc(), Booking.time_start.desc())))
    # Load possible conflicts in one query instead of one query per open record.
    open_items = [item for item in items if item.status in {"pending", "approved"}]
    occupied: dict[tuple[int, date], list[tuple[int, object, object]]] = {}
    if open_items:
        rows = db.execute(
            select(Booking.id, Booking.room_id, Booking.date, Booking.time_start, Booking.time_end).where(
                Booking.status.in_(BLOCKING_STATUSES),
                Booking.room_id.in_(list({item.room_id for item in open_items})),
                Booking.date >= min(item.date for item in open_items),
                Booking.date <= max(item.date for item in open_items),
            )
        )
        for booking_id, room_id, day, start, end in rows:
            occupied.setdefault((room_id, day), []).append((booking_id, start, end))
    result = []
    for item in items:
        data = booking_to_dict(item, include_admin_notice=True)
        data["has_conflict"] = item.status in {"pending", "approved"} and any(
            other_id != item.id and intervals_overlap(item.time_start, item.time_end, other_start, other_end)
            for other_id, other_start, other_end in occupied.get((item.room_id, item.date), [])
        )
        result.append(data)
    return add_attachments(db, items, result)


@router.get("/api/admin/booking-center/{booking_id}")
def booking_center_detail(booking_id: int, _: User = Depends(admin_read_user), db: Session = Depends(get_db)):
    stmt = (
        select(Booking)
        .options(
            joinedload(Booking.room).joinedload(Room.building),
            joinedload(Booking.owner),
            joinedload(Booking.cancelled_by),
            joinedload(Booking.archived_by),
            joinedload(Booking.department),
            selectinload(Booking.events).joinedload(BookingEvent.actor),
            selectinload(Booking.comments).joinedload(BookingComment.author),
            selectinload(Booking.comments).joinedload(BookingComment.resolved_by),
            selectinload(Booking.observers).joinedload(BookingObserver.user),
        )
        .where(Booking.id == booking_id)
    )
    item = db.scalars(stmt).unique().one_or_none()
    if not item:
        raise HTTPException(404, "Бронирование не найдено")
    data = add_attachments(
        db,
        [item],
        [booking_to_dict(item, include_events=True, include_admin_notice=True)],
    )[0]
    data["extra_rooms"] = [booking_to_dict(extra) for extra in extra_rooms_of(db, item)] if not item.parent_booking_id else []
    parent = db.get(Booking, item.parent_booking_id) if item.parent_booking_id else None
    data["parent"] = (
        {"id": parent.id, "title": parent.title, "room_number": parent.room.number, "status": parent.status}
        if parent
        else None
    )
    conflict = find_conflict(db, item.room_id, item.date, item.time_start, item.time_end, item.id)
    data["assessment"] = {
        "available": conflict is None,
        "message": (
            "Аудитория свободна, пересечений нет"
            if conflict is None
            else "Обнаружено пересечение с бронью на выбранную дату"
        ),
        "capacity_ok": not item.participants or capacity_limit(item.room) >= item.participants,
        "over_capacity": bool(item.participants and item.participants > item.room.capacity),
    }
    if data["assessment"]["capacity_ok"] and data["assessment"]["over_capacity"]:
        data["assessment"]["message"] += (
            f". Участников больше обычной вместимости ({item.room.capacity}) — понадобятся дополнительные места"
        )
    elif not data["assessment"]["capacity_ok"]:
        data["assessment"]["message"] += (
            f". Участников больше, чем вмещает аудитория ({capacity_limit(item.room)})"
        )
    return data


@router.get("/api/admin/users/search")
def search_registered_users(q: str = "", _: User = Depends(admin_read_user), db: Session = Depends(get_db)):
    needle = q.strip()
    stmt = select(User).where(User.is_active, User.role == "user")
    if needle:
        pattern = f"%{needle}%"
        stmt = stmt.where(
            or_(User.full_name.ilike(pattern), User.email.ilike(pattern), cast(User.id, String).ilike(pattern))
        )
    users = list(db.scalars(stmt.order_by(User.full_name).limit(20)))
    return [
        {
            "id": item.id,
            "full_name": item.full_name,
            "email": item.email,
            "avatar_url": item.avatar_url,
            "department": item.department,
        }
        for item in users
    ]


@router.put("/api/admin/booking-center/{booking_id}/observers")
def update_booking_observers(
    booking_id: int,
    payload: BookingObserversUpdate,
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    booking = get_booking_or_404(db, booking_id)
    ids = list(dict.fromkeys(payload.user_ids))
    if len(ids) > 5:
        raise HTTPException(422, "К заявке можно назначить не более пяти наблюдателей")
    users = (
        list(db.scalars(select(User).where(User.id.in_(ids), User.is_active, User.role == "user")))
        if ids
        else []
    )
    if len(users) != len(ids):
        raise HTTPException(422, "Один из выбранных пользователей не найден или недоступен")
    previous = set(db.scalars(select(BookingObserver.user_id).where(BookingObserver.booking_id == booking.id)))
    db.execute(BookingObserver.__table__.delete().where(BookingObserver.booking_id == booking.id))
    db.add_all(
        [BookingObserver(booking_id=booking.id, user_id=user_id, assigned_by_id=user.id) for user_id in ids]
    )
    added, removed = set(ids) - previous, previous - set(ids)
    if added or removed:
        record_event(
            db,
            booking,
            user,
            "observers_updated",
            "Изменён список наблюдателей",
            {"added_user_ids": sorted(added), "removed_user_ids": sorted(removed)},
        )
    db.commit()
    return {
        "observers": [
            {"id": item.id, "full_name": item.full_name, "email": item.email, "avatar_url": item.avatar_url}
            for item in sorted(users, key=lambda value: value.full_name)
        ]
    }


def _observed_booking(db: Session, booking_id: int, user: User) -> Booking:
    stmt = (
        select(Booking)
        .options(
            joinedload(Booking.room).joinedload(Room.building),
            joinedload(Booking.owner),
            joinedload(Booking.department),
            joinedload(Booking.cancelled_by),
            joinedload(Booking.archived_by),
            joinedload(Booking.decided_by),
            selectinload(Booking.events).joinedload(BookingEvent.actor),
            selectinload(Booking.comments).joinedload(BookingComment.author),
            selectinload(Booking.comments).joinedload(BookingComment.resolved_by),
            selectinload(Booking.observers).joinedload(BookingObserver.user),
        )
        .join(BookingObserver, BookingObserver.booking_id == Booking.id)
        .where(Booking.id == booking_id, BookingObserver.user_id == user.id)
    )
    item = db.scalars(stmt).unique().one_or_none()
    if not item:
        raise HTTPException(404, "Наблюдаемая заявка не найдена")
    return item


@router.get("/api/me/observed-bookings")
def observed_bookings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = (
        select(Booking)
        .options(
            joinedload(Booking.room).joinedload(Room.building),
            joinedload(Booking.owner),
            joinedload(Booking.department),
            joinedload(Booking.cancelled_by),
            joinedload(Booking.archived_by),
            joinedload(Booking.decided_by),
        )
        .join(BookingObserver, BookingObserver.booking_id == Booking.id)
        .where(BookingObserver.user_id == user.id)
        .order_by(Booking.created_at.desc())
    )
    items = list(db.scalars(stmt).unique())
    return add_attachments(db, items, [booking_to_dict(item) for item in items])


@router.get("/api/me/observed-bookings/{booking_id}")
def observed_booking_detail(booking_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = _observed_booking(db, booking_id, user)
    return add_attachments(db, [item], [booking_to_dict(item, include_events=True)])[0]


@router.post("/api/me/observed-bookings/{booking_id}/comments", status_code=201)
def add_observer_comment(
    booking_id: int,
    payload: BookingCommentCreate,
    user: User = Depends(csrf_protected),
    db: Session = Depends(get_db),
):
    booking = _observed_booking(db, booking_id, user)
    item = BookingComment(booking_id=booking.id, author_id=user.id, text=payload.text.strip())
    db.add(item)
    db.flush()
    record_event(db, booking, user, "comment_added", "Наблюдатель добавил комментарий", {"comment_id": item.id})
    db.commit()
    db.refresh(item)
    return {"id": item.id, "text": item.text, "author": user.full_name, "created_at": item.created_at.isoformat()}


@router.post("/api/admin/booking-center/{booking_id}/transfer", status_code=201)
def transfer_admin_booking(
    booking_id: int,
    payload: BookingTransferRequest,
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    require_booking_logistics(payload)
    original = get_booking_or_404(db, booking_id)
    return booking_to_dict(transfer_booking(db, original, payload, user))


@router.post("/api/admin/booking-center/{booking_id}/comments", status_code=201)
def add_booking_comment(
    booking_id: int,
    payload: BookingCommentCreate,
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    booking = get_booking_or_404(db, booking_id)
    item = BookingComment(booking_id=booking.id, author_id=user.id, text=payload.text.strip())
    db.add(item)
    db.flush()
    record_event(db, booking, user, "comment_added", "Добавлен рабочий комментарий", {"comment_id": item.id})
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "text": item.text,
        "author": user.full_name,
        "created_at": item.created_at.isoformat(),
        "resolved_at": None,
    }


@router.post("/api/admin/booking-center/{booking_id}/comments/{comment_id}/resolve")
def resolve_booking_comment(
    booking_id: int,
    comment_id: int,
    payload: BookingCommentResolve,
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    item = db.scalar(
        select(BookingComment).where(BookingComment.id == comment_id, BookingComment.booking_id == booking_id)
    )
    if not item:
        raise HTTPException(404, "Комментарий не найден")
    item.resolved_at = utc_now() if payload.resolved else None
    item.resolved_by_id = user.id if payload.resolved else None
    record_event(
        db,
        item.booking,
        user,
        "comment_resolved" if payload.resolved else "comment_reopened",
        "Рабочий вопрос закрыт" if payload.resolved else "Рабочий вопрос открыт повторно",
        {"comment_id": item.id},
    )
    db.commit()
    return {"ok": True}


def _history_value(value):
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


@router.put("/api/admin/booking-center/{booking_id}")
def update_admin_booking(
    booking_id: int,
    payload: BookingUpdate,
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    item = db.get(Booking, booking_id)
    if not item:
        raise HTTPException(404, "Бронирование не найдено")
    item = lock_booking_record(db, item)
    if item.status in CLOSED_BOOKING_STATUSES:
        raise HTTPException(409, "Закрытое бронирование нельзя изменять")
    values = payload.model_dump(exclude_unset=True)
    room_id = values.get("room_id", item.room_id)
    booking_date = values.get("date", item.date)
    start = values.get("time_start", item.time_start)
    end = values.get("time_end", item.time_end)
    schedule_changed = (room_id, booking_date, start, end) != (
        item.room_id,
        item.date,
        item.time_start,
        item.time_end,
    )
    if item.parent_booking_id and booking_date != item.date:
        raise HTTPException(409, "Дополнительная аудитория бронируется на день основной брони — перенесите основную бронь")
    set_extras = [] if item.parent_booking_id else extra_rooms_of(db, item, open_only=True)
    if schedule_changed:
        validate_booking_window(booking_date, start, end)
    target_room = db.get(Room, room_id)
    if not target_room:
        raise HTTPException(404, "Аудитория не найдена")
    if not target_room.is_active and (room_id != item.room_id or schedule_changed):
        raise HTTPException(409, "Аудитория отключена — выберите другую аудиторию")
    if values.get("department_id") is not None and not db.get(Department, values["department_id"]):
        raise HTTPException(404, "Подразделение не найдено")
    participants = values.get("participants") or item.participants
    if room_id != item.room_id or participants != item.participants:
        check_capacity(target_room, participants)
    lock_key = booking_date.toordinal() * 100000 + room_id
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    conflict = find_conflict(db, room_id, booking_date, start, end, item.id)
    if conflict:
        raise HTTPException(409, "Выбранная аудитория занята на эту дату")
    before = {
        "room_id": item.room_id,
        "date": item.date.isoformat(),
        "time_start": item.time_start.strftime("%H:%M"),
        "time_end": item.time_end.strftime("%H:%M"),
        "title": item.title,
    }
    changes = {
        key: {"before": _history_value(getattr(item, key)), "after": _history_value(value)}
        for key, value in values.items()
        if getattr(item, key) != value
    }
    for key, value in values.items():
        setattr(item, key, value)
    item.updated_at = utc_now()
    after = {
        "room_id": item.room_id,
        "date": item.date.isoformat(),
        "time_start": item.time_start.strftime("%H:%M"),
        "time_end": item.time_end.strftime("%H:%M"),
        "title": item.title,
    }
    record_event(
        db,
        item,
        user,
        "updated",
        "Параметры бронирования изменены",
        {"before": before, "after": after, "changes": changes},
    )
    if set_extras and schedule_changed:
        move_extra_rooms(db, set_extras, item, user)
    if item.status == "approved" and schedule_changed:
        reject_competing_requests(db, item, user)
    db.commit()
    return {"ok": True}


@router.post("/api/admin/booking-center/{booking_id}/archive")
def archive_admin_booking(
    booking_id: int,
    payload: BookingArchiveRequest,
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    item = get_booking_or_404(db, booking_id)
    set_booking_archived(db, item, user, payload.archived)
    return {"ok": True}


@router.post("/api/admin/booking-bulk/archive")
def archive_admin_bookings(
    payload: BookingBulkArchiveRequest,
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    return {"ok": True, "count": set_bookings_archived(db, payload.ids, user, payload.archived)}


@router.post("/api/admin/booking-bulk/delete")
def delete_admin_bookings(
    payload: BookingBulkRequest,
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    remove_unused_files(db, delete_booking_records(db, payload.ids, user))
    return {"ok": True}


@router.post("/api/admin/booking-center/{booking_id}/cancel")
def cancel_admin_booking(
    booking_id: int,
    payload: BookingCancelRequest,
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    item = get_booking_or_404(db, booking_id)
    cancel_booking_record(
        db,
        item,
        user,
        reason=payload.reason,
        comment=payload.comment,
        replacement_offered=payload.replacement_offered,
        notify_customer=payload.notify_customer,
    )
    return {"ok": True}


@router.delete("/api/admin/booking-center/{booking_id}")
def delete_admin_booking(
    booking_id: int,
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    item = get_booking_or_404(db, booking_id)
    remove_unused_files(db, delete_booking_records(db, [item.id], user))
    return {"ok": True}


@router.post("/api/admin/booking-center/{booking_id}/status")
def set_booking_status(
    booking_id: int,
    payload: BookingStatusRequest,
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    item = get_booking_or_404(db, booking_id)
    transition_booking_status(db, item, user, payload.status, payload.reason)
    return {"ok": True}
