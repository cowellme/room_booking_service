from datetime import date, datetime, time, timedelta
import hashlib
import uuid
from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from ..config import settings
from ..models import Booking, BookingEvent, BookingHistory, Department, Room, User
from ..schemas import BookingCreate
from ..timeutils import local_now, utc_now
from .booking_locks import lock_booking_rows
def validate_booking_window(booking_date: date, start: time, end: time) -> None:
    # The checks below count whole minutes: 10:00:59–10:30:01 would pass as 30 minutes.
    if any(value.second or value.microsecond or value.tzinfo for value in (start, end)):
        raise HTTPException(400, "Время указывается в часах и минутах, без секунд и часового пояса")
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute
    duration = end_minutes - start_minutes
    if start_minutes < settings.work_hours_start * 60 or end_minutes > settings.work_hours_end * 60:
        raise HTTPException(400, f"Бронирование доступно с {settings.work_hours_start:02d}:00 до {settings.work_hours_end:02d}:00")
    full_day = start_minutes == settings.work_hours_start * 60 and end_minutes == settings.work_hours_end * 60
    if duration <= 0 or (not full_day and not settings.min_booking_minutes <= duration <= settings.max_booking_minutes):
        raise HTTPException(400, f"Продолжительность бронирования — от {settings.min_booking_minutes} минут до {settings.max_booking_minutes // 60} часов")
    if not full_day and (start_minutes % settings.slot_minutes or end_minutes % settings.slot_minutes):
        raise HTTPException(400, f"Время должно быть кратно {settings.slot_minutes} минутам")


# Pending user requests are a soft reserve. Confirmed and completed records block the recorded interval;
# moderation still sees competing pending requests and decides which one wins.
BLOCKING_STATUSES = ("approved", "completed")


def overlap_filters(start: time, end: time):
    """SQL predicates for half-open intervals; consecutive bookings are allowed."""
    return Booking.time_start < end, Booking.time_end > start


def intervals_overlap(first_start: time, first_end: time, second_start: time, second_end: time) -> bool:
    """In-memory counterpart of :func:`overlap_filters`."""
    return first_start < second_end and first_end > second_start


def capacity_limit(room: Room) -> int:
    """Hard limit of people: the maximum with extra seating, or the regular capacity.

    Up to the regular capacity a request is ordinary; between the regular and the
    maximum it is accepted but flagged for the administrator (over_capacity).
    """
    return max(getattr(room, "max_capacity", None) or 0, room.capacity)


def check_capacity(room: Room, participants: int | None) -> None:
    limit = capacity_limit(room)
    if participants and participants > limit:
        raise HTTPException(400, f"Аудитория {room.number} вмещает {limit} чел., а участников заявлено {participants}")


def record_event(db: Session, booking: Booking, actor: User, event_type: str, summary: str, data: dict | None = None) -> None:
    db.add(BookingEvent(booking_id=booking.id, actor_id=actor.id, event_type=event_type,
                        summary=summary, data=data or {}))
    # Keep the legacy audit table populated for compatibility with existing reports.
    db.add(BookingHistory(booking_id=booking.id, actor_id=actor.id, action=event_type,
                          details=summary))


def find_conflict(db: Session, room_id: int, booking_date: date, start: time, end: time,
                  exclude_booking_id: int | None = None) -> Booking | None:
    stmt = select(Booking).where(and_(
        Booking.room_id == room_id, Booking.date == booking_date,
        Booking.status.in_(BLOCKING_STATUSES),
        *overlap_filters(start, end),
    ))
    if exclude_booking_id:
        stmt = stmt.where(Booking.id != exclude_booking_id)
    return db.scalar(stmt.order_by(Booking.time_start))


COMPETING_REJECT_REASON = "Аудитория занята: на эту дату подтверждено другое бронирование"


def reject_competing_requests(db: Session, booking: Booking, actor: User) -> int:
    """Close pending requests that can no longer be approved because `booking` now holds the slot.

    Without this they stay in moderation until the event starts and then expire
    as "not reviewed", so the requester learns about the refusal too late.
    """
    competing = lock_booking_rows(db, select(Booking).options(joinedload(Booking.owner)).where(
        Booking.room_id == booking.room_id, Booking.date == booking.date, Booking.status.in_(("pending", "in_progress")),
        Booking.time_start < booking.time_end, Booking.time_end > booking.time_start, Booking.id != booking.id,
    ).order_by(Booking.id))
    # A conflict on a main or extra room makes that day's kit unavailable.
    # Keep all other dates of the period independently reviewable.
    roots = {item.parent_booking_id or item.id for item in competing if item.series_id}
    if roots:
        seen = {item.id for item in competing}
        related = lock_booking_rows(db, select(Booking).where(
            Booking.status.in_(("pending", "in_progress")), Booking.series_id.is_not(None),
            or_(Booking.id.in_(roots), Booking.parent_booking_id.in_(roots)),
        ).order_by(Booking.id))
        competing.extend(item for item in related if item.id not in seen)
    now = utc_now()
    for item in competing:
        item.status = "rejected"
        item.updated_at = now
        item.decision_at = now
        item.decided_by_id = actor.id
        item.decision_reason = COMPETING_REJECT_REASON
        item.hold_expires_at = None
        record_event(db, item, actor, "rejected", "Заявка отклонена",
                     {"previous_status": "pending_or_in_progress", "reason": COMPETING_REJECT_REASON, "approved_booking_id": booking.id})
    return len(competing)


def find_own_duplicate(db: Session, owner_id: int, room_id: int, booking_date: date, start: time, end: time) -> Booking | None:
    """An overlapping open request of the same person for the same room and date."""
    return db.scalar(select(Booking).where(
        Booking.owner_id == owner_id, Booking.room_id == room_id, Booking.date == booking_date,
        Booking.status.in_(("pending", "in_progress", "approved")),
        *overlap_filters(start, end),
    ).limit(1))


def resolve_typed_department(db: Session, name: str, actor: User) -> Department:
    """Department typed by hand ("Нет в списке").

    A user's entry is stored for the booking only and does not appear in the
    shared directory until an administrator adds it, so typos do not spread.
    The requester's profile is never changed by a booking.
    """
    name = name.strip()
    department = db.scalar(select(Department).where(func.lower(Department.name) == name.lower()))
    if not department:
        code = "USER-" + hashlib.sha1(name.casefold().encode("utf-8")).hexdigest()[:10].upper()
        department = db.scalar(select(Department).where(Department.code == code))
    if not department:
        # Two requests may type the same new name at once: the second one reuses the
        # row the first one created instead of failing on the unique code.
        try:
            with db.begin_nested():
                department = Department(code=code, name=name, is_active=actor.role == "admin")
                db.add(department)
                db.flush()
        except IntegrityError:
            department = db.scalar(select(Department).where(Department.code == code))
            if not department:
                raise
    elif actor.role == "admin":
        department.is_active = True
    return department


MAX_USER_SERIES_RECORDS = 200
MAX_SERIES_RECORDS = 2000


def lock_booking_slot(db: Session, room_id: int, day: date) -> None:
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": day.toordinal() * 100000 + room_id})


def create_booking_period(db: Session, payload: BookingCreate, owner: User, *, commit: bool = True, **options) -> Booking:
    """Save an inclusive period atomically, using the existing series representation."""
    end = payload.date_end or payload.date
    if end == payload.date:
        return create_booking(db, payload, owner, commit=commit, **options)

    count = (end - payload.date).days + 1
    limit = MAX_SERIES_RECORDS if owner.role == "admin" else MAX_USER_SERIES_RECORDS
    room_count = len(payload.extra_rooms) + 1
    if count * room_count > limit:
        raise HTTPException(400, f"Слишком большой период: допустимо не больше {limit} записей. Сократите период или число аудиторий")
    series_id = str(uuid.uuid4())
    created_at = utc_now()
    created = []
    try:
        for offset in range(count):
            day = payload.date + timedelta(days=offset)
            entry = payload.model_copy(update={"date": day, "date_end": None})
            try:
                created.append(create_booking(db, entry, owner, commit=False, series_id=series_id,
                                              submitted_at=created_at, **options))
            except HTTPException as error:
                raise HTTPException(error.status_code, f"{day:%d.%m.%Y}: {error.detail}") from error
        if commit:
            db.commit()
    except Exception:
        db.rollback()
        raise
    return created[0]


def create_booking(db: Session, payload: BookingCreate, owner: User, *, source: str | None = None,
                   customer_name: str | None = None, customer_contact: str | None = None,
                   participants: int | None = None, commit: bool = True, series_id: str | None = None,
                   submitted_at: datetime | None = None) -> Booking:
    validate_booking_window(payload.date, payload.time_start, payload.time_end)
    room = db.scalar(select(Room).options(joinedload(Room.building)).where(Room.id == payload.room_id, Room.is_active))
    if not room:
        raise HTTPException(404, "Аудитория не найдена")
    department_id = payload.department_id
    raw_department_name = getattr(payload, "department_name", None)
    department_name = raw_department_name.strip() if raw_department_name else None
    check_capacity(room, participants if participants is not None else payload.participants)
    if department_id:
        chosen = db.get(Department, department_id)
        if not chosen:
            raise HTTPException(404, "Подразделение не найдено")
    if not department_id and department_name:
        department_id = resolve_typed_department(db, department_name, owner).id
    # Advisory lock serializes bookings for the same room/date in PostgreSQL.
    for room_id in sorted({payload.room_id, *(extra.room_id for extra in payload.extra_rooms)}):
        lock_booking_slot(db, room_id, payload.date)
    conflict = find_conflict(db, payload.room_id, payload.date, payload.time_start, payload.time_end)
    if conflict:
        raise HTTPException(409, "Аудитория уже занята на выбранную дату")
    if owner.role != "admin" and find_own_duplicate(db, owner.id, payload.room_id, payload.date, payload.time_start, payload.time_end):
        raise HTTPException(409, "У вас уже есть заявка на эту дату в этой аудитории")
    data = payload.model_dump()
    data.pop("extra_rooms", None)
    data.pop("date_end", None)
    requested_participants = data.pop("participants", None)
    data.pop("department_name", None)
    data["department_id"] = department_id
    payload_customer_name = data.pop("customer_name", None)
    payload_customer_contact = data.pop("customer_contact", None)
    data["booked_by"] = owner.full_name
    data["email"] = owner.email
    initial_status = "approved" if owner.role == "admin" else "pending"
    item = Booking(**data, owner_id=owner.id, status=initial_status,
                   source=source or ("admin_direct" if owner.role == "admin" else "self_service"),
                   customer_name=customer_name or payload_customer_name or owner.full_name,
                   customer_contact=customer_contact or payload_customer_contact or owner.email,
                   participants=participants if participants is not None else requested_participants,
                   hold_expires_at=None, created_at=submitted_at)
    try:
        db.add(item); db.flush()
        record_event(db, item, owner, "created", "Бронирование создано",
                     {"source": item.source, "room_id": item.room_id, "date": item.date.isoformat(),
                      "time_start": item.time_start.strftime("%H:%M"), "time_end": item.time_end.strftime("%H:%M")})
        if initial_status == "approved":
            record_event(db, item, owner, "approved", "Бронирование подтверждено администратором")
            reject_competing_requests(db, item, owner)
        extras = []
        if payload.extra_rooms:
            from .room_sets import create_extra_rooms
            extras = create_extra_rooms(db, item, payload.extra_rooms, owner)
        if series_id:
            item.series_id = series_id
            for extra in extras:
                extra.series_id = series_id
        if commit:
            db.commit()
            db.refresh(item)
    except Exception:
        db.rollback()
        raise
    item.room = room
    return item
