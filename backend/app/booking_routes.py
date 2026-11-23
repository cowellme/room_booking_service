"""User-facing booking, attachment and notification HTTP routes."""
from collections import defaultdict
from datetime import date
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session, joinedload

from .database import get_db
from .http_body import read_limited
from .models import Booking, BookingAttachment, BookingEvent, Room, User
from .schemas import (BOOKING_LOGISTICS_LABELS, BatchBookingCreate, BookingCancelRequest, BookingCreate,
                      ExtraRoomsAdd)
from .security import csrf_protected, current_user
from .serializers import booking_to_dict, calendar_booking_to_dict
from .services.attachments import (MAX_FILE_BYTES, add_attachments, delete_attachment, get_attachment_for,
                                   inline_allowed, remove_unused_files, replace_attachment, save_attachment,
                                   validate_attachment)
from .services.booking_lifecycle import cancel_booking_record, cancel_series_records, get_booking_or_404
from .services.bookings import create_booking_period as create_booking_service
from .services.operations import create_series
from .services.room_sets import create_extra_rooms

router = APIRouter(tags=["bookings"])
SECOND_BUILDING_NAME = "Второй учебный корпус"
CALENDAR_MAX_DAYS = 62
NOTIFICATION_EVENTS = ("in_progress", "approved", "rejected", "expired", "cancelled_by_admin", "transferred", "updated")


@router.get("/api/bookings")
def bookings(date_from: date, date_to: date, room_id: int | None = None,
             user: User = Depends(current_user), db: Session = Depends(get_db)):
    visibility = Booking.status.in_(("approved", "completed"))
    if date_to < date_from:
        raise HTTPException(400, "Дата окончания периода раньше даты начала")
    if (date_to - date_from).days > CALENDAR_MAX_DAYS:
        raise HTTPException(400, f"Календарь загружается периодами не длиннее {CALENDAR_MAX_DAYS} дней")
    stmt = select(Booking).options(
        joinedload(Booking.room).joinedload(Room.building), joinedload(Booking.owner), joinedload(Booking.department),
        joinedload(Booking.decided_by), joinedload(Booking.cancelled_by), joinedload(Booking.archived_by),
    ).where(Booking.date >= date_from, Booking.date <= date_to, visibility)
    if room_id:
        stmt = stmt.where(Booking.room_id == room_id)
    result = []
    masked = set()
    for item in db.scalars(stmt.order_by(Booking.date, Booking.time_start)):
        if user.role == "admin" or item.room.building.name == SECOND_BUILDING_NAME:
            result.append(calendar_booking_to_dict(item, include_private=user.role == "admin",
                                                   include_reference=item.owner_id == user.id))
            continue
        key = (item.room_id, item.date.isoformat())
        if key not in masked:
            masked.add(key)
            result.append({"id": f"busy-{key[0]}-{key[1]}", "room_id": key[0], "date": key[1],
                           "status": "approved", "restricted": True})
    return result


@router.post("/api/bookings", status_code=201)
def create_booking_without_file(payload: BookingCreate, user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(422, "Перед отправкой заявки прикрепите файл")
    return create_booking(payload, user, db)


def create_booking(payload: BookingCreate, user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    require_request_details(payload, user)
    return booking_to_dict(create_booking_service(db, payload, user))


def require_request_details(payload: BookingCreate | BatchBookingCreate, user: User) -> None:
    missing = [label for label, present in (
        ("количество участников", payload.participants),
        ("ФИО ответственного", len((payload.customer_name or "").strip()) >= 2),
        ("подразделение", payload.department_id or payload.department_name),
        ("номер заявки", (payload.external_reference or "").strip()),
    ) if not present]
    if missing:
        raise HTTPException(422, "Заполните обязательные поля: " + ", ".join(missing))
    require_booking_logistics(payload)


def require_booking_logistics(payload: BookingCreate | BatchBookingCreate) -> None:
    missing = [label for key, label in BOOKING_LOGISTICS_LABELS.items() if getattr(payload, key) is None]
    if missing:
        raise HTTPException(422, "Ответьте на обязательные вопросы: " + ", ".join(missing))


@router.get("/api/me/bookings")
def my_bookings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Booking).options(
        joinedload(Booking.room).joinedload(Room.building), joinedload(Booking.owner),
        joinedload(Booking.cancelled_by), joinedload(Booking.archived_by), joinedload(Booking.decided_by),
    ).where(Booking.owner_id == user.id).order_by(Booking.date.desc(), Booking.time_start)
    items = list(db.scalars(stmt))
    relevant = db.execute(select(BookingEvent.booking_id, BookingEvent.id, BookingEvent.created_at,
                                 BookingEvent.data, User.full_name)
                          .select_from(BookingEvent).join(Booking, Booking.id == BookingEvent.booking_id)
                          .outerjoin(User, User.id == BookingEvent.actor_id)
                          .where(Booking.owner_id == user.id, BookingEvent.event_type == "attachment_replaced")
                          .order_by(BookingEvent.created_at, BookingEvent.id))
    replacements = defaultdict(list)
    for row in relevant:
        replacements[row.booking_id].append({
            "id": row.id, "at": row.created_at.isoformat(), "actor": row.full_name,
            "before": row.data.get("before"), "after": row.data.get("after"),
            "replacement_id": row.data.get("replacement_id"),
        })
    return add_attachments(db, items, [
        {**booking_to_dict(item), "file_replacements": replacements[item.id]} for item in items
    ])


@router.post("/api/me/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: int, payload: BookingCancelRequest, user: User = Depends(csrf_protected),
                   db: Session = Depends(get_db)):
    item = get_booking_or_404(db, booking_id)
    if item.owner_id != user.id and user.role != "admin":
        raise HTTPException(404, "Бронирование не найдено")
    cancel_booking_record(db, item, user, reason=payload.reason, comment=payload.comment,
                          replacement_offered=payload.replacement_offered,
                          notify_customer=payload.notify_customer)
    return {"ok": True}


@router.post("/api/me/booking-series/{series_id}/cancel")
def cancel_my_series(series_id: str, payload: BookingCancelRequest, user: User = Depends(csrf_protected),
                     db: Session = Depends(get_db)):
    count = cancel_series_records(db, series_id, user, reason=payload.reason, comment=payload.comment,
                                  replacement_offered=payload.replacement_offered,
                                  notify_customer=payload.notify_customer)
    return {"ok": True, "cancelled": count}


def _add_extra_rooms(db: Session, main: Booking, payload: ExtraRoomsAdd, actor: User,
                     status: str | None) -> list[dict]:
    try:
        items = create_extra_rooms(db, main, payload.extra_rooms, actor, status=status)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return [booking_to_dict(db.get(Booking, item.id)) for item in items]


@router.post("/api/me/bookings/{booking_id}/extra-rooms", status_code=201)
def add_my_extra_rooms_route(booking_id: int, payload: ExtraRoomsAdd, user: User = Depends(csrf_protected),
                             db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(403, "В отправленной заявке можно редактировать только файл")
    return add_my_extra_rooms(booking_id, payload, user, db)


def add_my_extra_rooms(booking_id: int, payload: ExtraRoomsAdd, user: User = Depends(csrf_protected),
                       db: Session = Depends(get_db)):
    main = get_booking_or_404(db, booking_id)
    if main.owner_id != user.id and user.role != "admin":
        raise HTTPException(404, "Бронирование не найдено")
    status = "approved" if user.role == "admin" and main.status == "approved" else "pending"
    return _add_extra_rooms(db, main, payload, user, status)


async def _read_upload(request: Request) -> bytes:
    return await read_limited(request, MAX_FILE_BYTES, "Размер файла должен быть не более 20 МБ")


async def _submission_with_file(request: Request, schema):
    metadata_limit = 65536
    raw = await read_limited(request, MAX_FILE_BYTES + metadata_limit + 4, "Размер файла должен быть не более 20 МБ")
    size = int.from_bytes(raw[:4], "big")
    if len(raw) < 5 or not 0 < size <= metadata_limit or len(raw) < size + 4:
        raise HTTPException(422, "Прикрепите файл перед отправкой заявки")
    try:
        meta = json.loads(raw[4:4 + size])
        if not isinstance(meta, dict) or not isinstance(meta.get("name"), str):
            raise ValueError
        payload = schema.model_validate(meta.get("booking"))
    except ValidationError as error:
        raise HTTPException(422, "; ".join(item["msg"] for item in error.errors())) from None
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(422, "Не удалось прочитать заявку и вложение") from None
    content = raw[4 + size:]
    validate_attachment(content, meta["name"])
    return payload, content, meta["name"]


@router.post("/api/me/request-with-file", status_code=201)
async def submit_booking_with_file(request: Request, series: bool = False, user: User = Depends(csrf_protected),
                                   db: Session = Depends(get_db)):
    payload, content, name = await _submission_with_file(request, BatchBookingCreate if series else BookingCreate)
    require_request_details(payload, user)
    stored_name = None
    try:
        if series:
            item = create_series(db, payload, user, status="pending", source="self_service", commit=False)[0]
        else:
            item = create_booking_service(db, payload, user, commit=False)
        db.flush()
        target = {"series_id": item.series_id} if item.series_id else {"booking_id": item.id}
        saved = save_attachment(db, user, content, name, **target, commit=False)
        stored_name = db.get(BookingAttachment, saved["id"]).stored_name
        db.commit()
    except Exception:
        db.rollback()
        if stored_name:
            remove_unused_files(db, [stored_name])
        raise
    return {"id": item.id, "series_id": item.series_id}


@router.put("/api/me/attachments/{attachment_id}")
async def replace_my_attachment(attachment_id: int, request: Request, user: User = Depends(csrf_protected),
                                db: Session = Depends(get_db)):
    return replace_attachment(db, user, attachment_id, await _read_upload(request), request.headers.get("x-file-name"))


@router.post("/api/bookings/{booking_id}/attachments", status_code=201)
async def upload_booking_attachment(booking_id: int, request: Request, user: User = Depends(csrf_protected),
                                    db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(403, "Пользователь может только заменить файл в своей заявке")
    return save_attachment(db, user, await _read_upload(request), request.headers.get("x-file-name"),
                           booking_id=booking_id)


@router.post("/api/booking-series/{series_id}/attachments", status_code=201)
async def upload_series_attachment(series_id: str, request: Request, user: User = Depends(csrf_protected),
                                   db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(403, "Пользователь может только заменить файл в своей заявке")
    return save_attachment(db, user, await _read_upload(request), request.headers.get("x-file-name"),
                           series_id=series_id)


@router.get("/api/attachments/{attachment_id}")
def open_attachment(attachment_id: int, download: bool = False, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    item, path = get_attachment_for(db, user, attachment_id)
    inline = inline_allowed(item) and not download
    headers = {} if inline and item.content_type == "application/pdf" else {
        "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
    }
    return FileResponse(path, media_type=item.content_type, filename=item.original_name,
                        content_disposition_type="inline" if inline else "attachment", headers=headers)


@router.delete("/api/attachments/{attachment_id}")
def remove_attachment(attachment_id: int, user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(403, "Обязательный файл можно только заменить")
    delete_attachment(db, user, attachment_id)
    return {"ok": True}


@router.get("/api/me/notifications")
def my_notifications(after: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(BookingEvent).join(Booking, BookingEvent.booking_id == Booking.id).options(
        joinedload(BookingEvent.booking).joinedload(Booking.room).joinedload(Room.building),
    ).where(
        Booking.owner_id == user.id, BookingEvent.id > after,
        BookingEvent.event_type.in_(NOTIFICATION_EVENTS),
        or_(BookingEvent.actor_id != user.id, BookingEvent.event_type == "expired"),
        func.coalesce(cast(BookingEvent.data["notify_customer"].as_string(), String), "true").not_in(("false", "0")),
    )
    items = (list(db.scalars(stmt.order_by(BookingEvent.id).limit(500))) if after else
             list(reversed(list(db.scalars(stmt.order_by(BookingEvent.id.desc()).limit(30))))))
    result = []
    for event in items:
        booking = event.booking
        data = event.data or {}
        series_id = data.get("series_id") or (f"set-{data['set_id']}" if data.get("set_id") else None)
        last = result[-1] if result else None
        if (series_id and last and last["series_id"] == series_id and last["type"] == event.event_type
                and last["reason"] == data.get("reason")):
            last["id"] = event.id
            last["series_count"] += 1
            last["date_end"] = max(last["date_end"], booking.date.isoformat())
            last["date"] = min(last["date"], booking.date.isoformat())
            continue
        result.append({
            "id": event.id, "type": event.event_type, "summary": event.summary,
            "booking_id": event.booking_id, "title": booking.title,
            "date": booking.date.isoformat(), "date_end": booking.date.isoformat(),
            "time_start": booking.time_start.strftime("%H:%M"),
            "room_number": booking.room.number, "building": booking.room.building.name,
            "reason": data.get("reason"), "series_id": series_id, "series_count": 1,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        })
    for entry in result:
        if entry["series_count"] > 1 and str(entry["series_id"]).startswith("set-"):
            entry["summary"] = f"{entry['summary']} — комплект, аудиторий: {entry['series_count']}"
        elif entry["series_count"] > 1:
            entry["summary"] = f"{entry['summary']} — серия, дат: {entry['series_count']}"
    return result
