from collections import defaultdict
from datetime import timedelta
import uuid

from fastapi import HTTPException
from sqlalchemy import select, text, func
from sqlalchemy.orm import Session, joinedload

from ..models import Booking, Department, Room, User
from ..timeutils import utc_now
from ..schemas import BatchBookingCreate, BookingTransferRequest, SeriesAvailabilityRequest, ServiceBlockCreate
from .bookings import (BLOCKING_STATUSES, check_capacity, find_conflict, find_own_duplicate, record_event,
                       reject_competing_requests, resolve_typed_department, validate_booking_window, validate_booking_lead_time)
from .booking_lifecycle import ensure_booking_open
from .booking_locks import lock_booking_record
from .attachments import copy_booking_attachments
from .room_sets import extra_rooms_of, move_extra_rooms


def _dates(start, end, weekdays=None):
    current = start
    while current <= end:
        if weekdays is None or current.weekday() in weekdays:
            yield current
        current += timedelta(days=1)


def _lock(db: Session, room_id: int, booking_date) -> None:
    key = booking_date.toordinal() * 100000 + room_id
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


# One request must stay reviewable: a user series is capped well below what an administrator may create.
MAX_USER_SERIES_RECORDS = 200
MAX_SERIES_RECORDS = 2000


def create_series(db: Session, payload: BatchBookingCreate, actor: User, *, status: str = "approved", source: str = "admin_batch") -> list[Booking]:
    if not payload.department_id and payload.department_name and payload.department_name.strip():
        payload.department_id = resolve_typed_department(db, payload.department_name, actor).id
    if payload.department_id:
        chosen = db.get(Department, payload.department_id)
        if not chosen:
            raise HTTPException(404, "Подразделение не найдено")
    dates = list(_dates(payload.date, payload.date_end, set(payload.weekdays)))
    if not dates:
        raise HTTPException(400, "В выбранном периоде нет подходящих дней")
    validate_booking_lead_time(dates[0])
    limit = MAX_SERIES_RECORDS if actor.role == "admin" else MAX_USER_SERIES_RECORDS
    if len(dates) * len(payload.room_ids) > limit:
        raise HTTPException(400, f"Слишком большая серия: {len(dates) * len(payload.room_ids)} бронирований, допустимо не больше {limit}. Сократите период или число аудиторий")
    # Rooms in id order and dates ascending: every multi-room operation takes the
    # room/day locks in the same order, so two of them cannot wait on each other.
    rooms = list(db.scalars(select(Room).options(joinedload(Room.building)).where(
        Room.id.in_(payload.room_ids), Room.is_active,
    ).order_by(Room.id)))
    if len(rooms) != len(payload.room_ids):
        raise HTTPException(404, "Одна или несколько аудиторий не найдены")
    for room in rooms:
        check_capacity(room, payload.participants)
    for day in dates:
        validate_booking_window(day, payload.time_start, payload.time_end)
        for room in rooms:
            _lock(db, room.id, day)
            conflict = find_conflict(db, room.id, day, payload.time_start, payload.time_end)
            if conflict:
                raise HTTPException(409, f"Серия пересекается с существующей бронью: {day.strftime('%d.%m.%Y')}, аудитория {room.number}")
            if actor.role != "admin" and find_own_duplicate(db, actor.id, room.id, day, payload.time_start, payload.time_end):
                raise HTTPException(409, f"У вас уже есть заявка на это время: {day.strftime('%d.%m.%Y')}, аудитория {room.number}")
    series_id = str(uuid.uuid4())
    created = []
    submitted_at = utc_now()
    try:
        for day in dates:
            for room in rooms:
                item = Booking(
                    room_id=room.id, owner_id=actor.id, date=day,
                    time_start=payload.time_start, time_end=payload.time_end,
                    title=payload.title.strip(), booking_type=payload.booking_type,
                    group_name=payload.group_name, teacher=payload.teacher,
                    booked_by=actor.full_name, email=actor.email, comment=payload.comment,
                    requested_equipment=payload.requested_equipment, participants=payload.participants,
                    catering_required=payload.catering_required, technical_support_required=payload.technical_support_required, source=source, customer_name=payload.customer_name or actor.full_name,
                    customer_contact=payload.customer_contact, department_id=payload.department_id,
                    external_channel=payload.external_channel, external_reference=payload.external_reference,
                    external_url=payload.external_url, series_id=series_id,
                    status=status, record_kind="booking", created_at=submitted_at,
                )
                db.add(item); db.flush()
                record_event(db, item, actor, "series_created", "Бронирование создано в серии", {"series_id": series_id})
                if status == "approved":
                    reject_competing_requests(db, item, actor)
                created.append(item)
        db.commit()
    except Exception:
        db.rollback(); raise
    return created


def series_conflicts(db: Session, payload: SeriesAvailabilityRequest) -> dict:
    """Dates of a planned series on which each room is already taken."""
    dates = list(_dates(payload.date, payload.date_end, set(payload.weekdays)))
    if not dates:
        return {"dates": [], "busy": {}}
    validate_booking_lead_time(dates[0])
    for day in dates:
        validate_booking_window(day, payload.time_start, payload.time_end)
    stmt = select(Booking.room_id, Booking.date).where(
        Booking.date.in_(dates), Booking.status.in_(BLOCKING_STATUSES),
        Booking.time_start < payload.time_end, Booking.time_end > payload.time_start,
    )
    if payload.room_ids:
        stmt = stmt.where(Booking.room_id.in_(payload.room_ids))
    busy: dict[str, set[str]] = defaultdict(set)
    for room_id, day in db.execute(stmt):
        busy[str(room_id)].add(day.isoformat())
    return {"dates": [day.isoformat() for day in dates], "busy": {key: sorted(value) for key, value in busy.items()}}


def transfer_booking(db: Session, original: Booking, payload: BookingTransferRequest, actor: User) -> Booking:
    original = lock_booking_record(db, original)
    ensure_booking_open(original)
    validate_booking_lead_time(payload.date)
    validate_booking_window(payload.date, payload.time_start, payload.time_end)
    room = db.scalar(select(Room).options(joinedload(Room.building)).where(Room.id == payload.room_id, Room.is_active))
    if not room:
        raise HTTPException(404, "Аудитория не найдена")
    check_capacity(room, payload.participants or original.participants)
    if payload.department_id and not db.get(Department, payload.department_id):
        raise HTTPException(404, "Подразделение не найдено")
    _lock(db, room.id, payload.date)
    conflict = find_conflict(db, room.id, payload.date, payload.time_start, payload.time_end, original.id)
    if conflict:
        raise HTTPException(409, "Новое время уже занято")
    if original.parent_booking_id:
        raise HTTPException(409, "Дополнительную аудиторию нельзя перенести отдельно — перенесите основную бронь или снимите аудиторию из комплекта")
    extras = extra_rooms_of(db, original, open_only=True)
    # A single booking stays single after a transfer: the chain is kept by previous_booking_id.
    series_id = original.series_id
    sent = payload.model_fields_set

    def kept(field: str):
        # Fields the form did not send are carried over from the original booking.
        return getattr(payload, field) if field in sent else getattr(original, field)

    item = Booking(
        room_id=room.id, owner_id=original.owner_id, date=payload.date,
        time_start=payload.time_start, time_end=payload.time_end,
        title=payload.title.strip(), booking_type=kept("booking_type"),
        group_name=kept("group_name"), teacher=kept("teacher"),
        booked_by=original.booked_by, email=original.email,
        comment=kept("comment"), requested_equipment=kept("requested_equipment") or [],
        catering_required=payload.catering_required, technical_support_required=payload.technical_support_required,
        participants=payload.participants or original.participants,
        source="transfer", customer_name=original.customer_name,
        customer_contact=original.customer_contact, department_id=payload.department_id or original.department_id,
        external_channel=payload.external_channel or original.external_channel,
        external_reference=payload.external_reference or original.external_reference,
        external_url=payload.external_url or original.external_url,
        series_id=series_id, previous_booking_id=original.id,
        # A request still in moderation stays a request after the transfer.
        transfer_reason=payload.reason.strip(), status="pending" if original.status == "pending" else "approved",
        record_kind="booking",
    )
    try:
        db.add(item); db.flush()
        original.status = "transferred"
        original.transfer_reason = payload.reason.strip()
        record_event(db, original, actor, "transferred", "Бронирование перенесено", {"new_booking_id": item.id, "reason": payload.reason, "notify_customer": payload.notify_customer})
        record_event(db, item, actor, "created_from_transfer", "Создано в результате переноса", {"previous_booking_id": original.id, "reason": payload.reason})
        copy_booking_attachments(db, original, item)
        move_extra_rooms(db, extras, item, actor)
        if item.status == "approved":
            reject_competing_requests(db, item, actor)
        db.commit(); db.refresh(item)
    except Exception:
        db.rollback(); raise
    item.room = room
    return item


def create_service_blocks(db: Session, payload: ServiceBlockCreate, actor: User) -> list[Booking]:
    dates = list(_dates(payload.date, payload.date_end))
    # 100 rooms for a year would be 36 600 records in one transaction: same cap as a series.
    if len(dates) * len(payload.room_ids) > MAX_SERIES_RECORDS:
        raise HTTPException(400, f"Слишком много блокировок за раз: {len(dates) * len(payload.room_ids)}, допустимо не больше {MAX_SERIES_RECORDS}. Сократите период или число аудиторий")
    rooms = list(db.scalars(select(Room).options(joinedload(Room.building)).where(
        Room.id.in_(payload.room_ids), Room.is_active,
    ).order_by(Room.id)))
    if len(rooms) != len(payload.room_ids):
        raise HTTPException(404, "Одна или несколько аудиторий не найдены")
    for day in dates:
        validate_booking_window(day, payload.time_start, payload.time_end, allow_started=True)
        for room in rooms:
            _lock(db, room.id, day)
            if find_conflict(db, room.id, day, payload.time_start, payload.time_end):
                raise HTTPException(409, f"Нельзя создать блокировку: {day.strftime('%d.%m.%Y')}, аудитория {room.number} уже занята")
    series_id = str(uuid.uuid4())
    created = []
    submitted_at = utc_now()
    try:
        for day in dates:
            for room in rooms:
                item = Booking(
                    room_id=room.id, owner_id=actor.id, date=day,
                    time_start=payload.time_start, time_end=payload.time_end,
                    title=payload.title.strip(), booking_type="service",
                    booked_by=actor.full_name, email=actor.email,
                    comment=payload.reason.strip(), requested_equipment=[],
                    source="service_block", customer_name="Служебная блокировка",
                    status="approved", record_kind=payload.record_kind, series_id=series_id,
                )
                db.add(item); db.flush()
                record_event(db, item, actor, "service_block_created", "Создана служебная блокировка", {"kind": payload.record_kind, "reason": payload.reason, "series_id": series_id})
                reject_competing_requests(db, item, actor)
                created.append(item)
        db.commit()
    except Exception:
        db.rollback(); raise
    return created
