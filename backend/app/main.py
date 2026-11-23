from contextlib import asynccontextmanager
import asyncio
from collections import defaultdict
from datetime import date
import logging
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, joinedload, selectinload
from .config import settings
from .database import get_db
from . import admin_booking_routes, auth_routes, booking_routes, moderation_routes, profile_routes
from .chat import router as chat_router
from .moderation_workspace import router as moderation_workspace_router
from .models import Booking, Building, Department, DepartmentCurator, Room, User
from .schemas import (AvailabilityRequest, BookingCancelRequest, BookingCreate, BatchBookingCreate, BuildingCreate, DepartmentCreate, PhoneBookingCreate,
                      RoomCreate, SeriesAvailabilityRequest,
                      SeriesStatusRequest, ServiceBlockCreate)
from .security import admin_read_user, admin_user, csrf_protected, current_user
from .serializers import booking_to_dict, room_to_dict
from .services.bookings import (create_booking_period as create_booking_service, validate_booking_window)
from .timeutils import local_now, local_today
from .services.availability import build_availability, equipment_categories as _equipment_categories  # noqa: F401
from .services.booking_lifecycle import (cancel_series_records,
                                         transition_series_status)
from .services.operations import create_series, create_service_blocks, series_conflicts
from .services.analytics import build_analytics
from .services.lifecycle_worker import lifecycle_loop

# Backward-compatible public names used by tests, scripts and older integrations.
auth_router = auth_routes.router
change_password = auth_routes.change_password
forgot_password = auth_routes.forgot_password
login = auth_routes.login
logout = auth_routes.logout
me = auth_routes.me
register = auth_routes.register
request_registration_code = auth_routes.request_registration_code
reset_password = auth_routes.reset_password
set_new_password = auth_routes.set_new_password
user_json = auth_routes.user_json

booking_router = booking_routes.router
SECOND_BUILDING_NAME = booking_routes.SECOND_BUILDING_NAME
_add_extra_rooms = booking_routes._add_extra_rooms
_read_upload = booking_routes._read_upload
_submission_with_file = booking_routes._submission_with_file
add_my_extra_rooms = booking_routes.add_my_extra_rooms
add_my_extra_rooms_route = booking_routes.add_my_extra_rooms_route
bookings = booking_routes.bookings
cancel_booking = booking_routes.cancel_booking
cancel_my_series = booking_routes.cancel_my_series
create_booking = booking_routes.create_booking
create_booking_without_file = booking_routes.create_booking_without_file
my_bookings = booking_routes.my_bookings
my_notifications = booking_routes.my_notifications
open_attachment = booking_routes.open_attachment
remove_attachment = booking_routes.remove_attachment
replace_my_attachment = booking_routes.replace_my_attachment
require_booking_logistics = booking_routes.require_booking_logistics
require_request_details = booking_routes.require_request_details
submit_booking_with_file = booking_routes.submit_booking_with_file
upload_booking_attachment = booking_routes.upload_booking_attachment
upload_series_attachment = booking_routes.upload_series_attachment

profile_router = profile_routes.router
UPLOAD_DIR = profile_routes.UPLOAD_DIR
delete_avatar = profile_routes.delete_avatar
extra_rooms_guide_status = profile_routes.extra_rooms_guide_status
mark_extra_rooms_guide_seen = profile_routes.mark_extra_rooms_guide_seen
update_profile = profile_routes.update_profile
upload_avatar = profile_routes.upload_avatar

moderation_router = moderation_routes.router
approve = moderation_routes.approve
moderation = moderation_routes.moderation
reject = moderation_routes.reject

admin_booking_router = admin_booking_routes.router
_history_value = admin_booking_routes._history_value
_observed_booking = admin_booking_routes._observed_booking
add_admin_extra_rooms = admin_booking_routes.add_admin_extra_rooms
add_booking_comment = admin_booking_routes.add_booking_comment
add_observer_comment = admin_booking_routes.add_observer_comment
archive_admin_booking = admin_booking_routes.archive_admin_booking
archive_admin_bookings = admin_booking_routes.archive_admin_bookings
booking_center = admin_booking_routes.booking_center
booking_center_detail = admin_booking_routes.booking_center_detail
cancel_admin_booking = admin_booking_routes.cancel_admin_booking
delete_admin_booking = admin_booking_routes.delete_admin_booking
delete_admin_bookings = admin_booking_routes.delete_admin_bookings
observed_booking_detail = admin_booking_routes.observed_booking_detail
observed_bookings = admin_booking_routes.observed_bookings
resolve_booking_comment = admin_booking_routes.resolve_booking_comment
search_registered_users = admin_booking_routes.search_registered_users
set_booking_status = admin_booking_routes.set_booking_status
transfer_admin_booking = admin_booking_routes.transfer_admin_booking
update_admin_booking = admin_booking_routes.update_admin_booking
update_booking_observers = admin_booking_routes.update_booking_observers




@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.seed_demo_data: logger.warning("SEED_DEMO_DATA ignored: demo catalog seeding is disabled")
    # Fine on a laptop, not on a public server: say so in the log on every start.
    if not settings.allowed_email_domains:
        logger.warning("ALLOWED_EMAIL_DOMAINS is empty: anyone with a confirmed mailbox on any domain can register")
    if not settings.cookie_secure:
        logger.warning("COOKIE_SECURE=false: the session cookie is sent over plain HTTP; use HTTPS and true in production")
    stop = asyncio.Event()
    task = (asyncio.create_task(lifecycle_loop(stop, settings.lifecycle_interval_seconds), name="booking-lifecycle")
            if settings.lifecycle_worker_enabled else None)
    try:
        yield
    finally:
        stop.set()
        if task is not None:
            # Finish the current bounded DB transaction before shutting down.
            await task


app = FastAPI(title="Room Booking API", version="2.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)
app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(booking_router)
app.include_router(moderation_router)
app.include_router(admin_booking_router)
app.include_router(chat_router)
app.include_router(moderation_workspace_router)
app.mount("/api/uploads", StaticFiles(directory=UPLOAD_DIR.parent), name="uploads")
app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins), allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type", "X-CSRF-Token", "X-File-Name"])
logger = logging.getLogger("room_booking")

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    if settings.cookie_secure: response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.get("/api/health")
def health(): return {"status": "ok"}

@app.get("/api/ready")
def ready(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1")); return {"status": "ready"}


@app.get("/api/buildings")
def buildings(db: Session = Depends(get_db)):
    return [{"id": b.id, "name": b.name, "address": b.address, "image": b.image, "color": b.color} for b in db.scalars(select(Building).order_by(Building.id))]


@app.get("/api/departments")
def departments(_: User = Depends(current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(Department).options(selectinload(Department.curators)).where(Department.is_active).order_by(Department.name, Department.id))
    return [{"id": item.id, "code": item.code, "name": item.name,
             "curators": [{"id": curator.id, "full_name": curator.full_name, "contact": curator.contact} for curator in item.curators]}
            for item in items]


@app.get("/api/public/departments")
def public_departments(db: Session = Depends(get_db)):
    items = db.scalars(select(Department).where(Department.is_active).order_by(Department.name, Department.id))
    return [{"id": item.id, "name": item.name} for item in items]


@app.post("/api/admin/departments", status_code=201)
def create_department(payload: DepartmentCreate, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    if payload.code is None:
        from .services.bookings import resolve_typed_department
        existing = next((item for item in db.scalars(select(Department))
                         if item.name.strip().casefold() == payload.name.casefold()), None)
        if existing and existing.is_active:
            raise HTTPException(409, "Подразделение с таким названием уже существует")
        # Preserve identifiers and existing curators when reactivating a department.
        item = existing or resolve_typed_department(db, payload.name, _)
        item.is_active = True
        db.commit(); db.refresh(item)
        return {"id": item.id, "code": item.code, "name": item.name}
    code = payload.code.strip()
    # ilike would treat "_" and "%" in a code as wildcards and match a different department.
    existing = db.scalar(select(Department).where(func.lower(Department.code) == code.lower()))
    if existing and existing.is_active:
        raise HTTPException(409, "Подразделение с таким кодом уже существует")
    item = existing or Department(code=code)
    item.name = payload.name.strip(); item.is_active = True
    item.curators = [DepartmentCurator(full_name=name.strip()) for name in payload.curators if name.strip()]
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "code": item.code, "name": item.name}



@app.delete("/api/admin/departments/{department_id}")
def delete_department(department_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    item = db.get(Department, department_id)
    if not item or not item.is_active: raise HTTPException(404, "Подразделение не найдено")
    # Bookings keep a foreign key to the department, so a used one is only hidden from the directory.
    if db.scalar(select(Booking.id).where(Booking.department_id == item.id).limit(1)):
        item.is_active = False; db.commit()
        return {"ok": True, "archived": True}
    db.delete(item); db.commit()
    return {"ok": True, "archived": False}

@app.get("/api/rooms")
def rooms(building_id: int | None = None, min_capacity: int = 0,
          search: str = "", db: Session = Depends(get_db)):
    stmt = select(Room).options(joinedload(Room.building)).where(
        Room.is_active, func.greatest(Room.capacity, func.coalesce(Room.max_capacity, 0)) >= min_capacity)
    if building_id: stmt = stmt.where(Room.building_id == building_id)
    if search: stmt = stmt.where(Room.number.ilike(f"%{search}%") | Room.name.ilike(f"%{search}%"))
    return [room_to_dict(r) for r in db.scalars(stmt.order_by(Room.building_id, Room.number))]


@app.get("/api/rooms/occupancy")
def room_occupancy(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Live state of every room that still has something scheduled today.

    A room missing from the answer is free until the end of the day. Back-to-back
    records are merged, so "until" is the moment the room really becomes free.
    """
    now = local_now(); current = now.time()
    remaining = db.scalars(select(Booking).options(joinedload(Booking.room).joinedload(Room.building)).where(
        Booking.date == now.date(), Booking.status == "approved", Booking.time_end > current,
    ).order_by(Booking.room_id, Booking.time_start, Booking.time_end))
    by_room: dict[int, list[Booking]] = defaultdict(list)
    for item in remaining:
        by_room[item.room_id].append(item)
    result = {}
    for room_id, records in by_room.items():
        first = records[0]
        if user.role != "admin" and first.room.building.name != SECOND_BUILDING_NAME:
            result[str(room_id)] = {"occupied": first.time_start <= current, "restricted": True}
            continue
        if first.time_start > current:
            result[str(room_id)] = {"occupied": False, "free_until": first.time_start.strftime("%H:%M")}
            continue
        until = first.time_end
        for following in records[1:]:
            if following.time_start > until: break
            until = max(until, following.time_end)
        result[str(room_id)] = {"occupied": True, "until": until.strftime("%H:%M"), "title": first.title,
                                "kind": first.record_kind}
    return result


def _user_availability_view(result: dict) -> dict:
    """Remove requester identities and internal pending-request data."""
    safe = {"summary": dict(result["summary"])}
    for group in ("free", "occupied", "alternatives"):
        safe[group] = []
        for source in result[group]:
            item = dict(source)
            if item.get("conflict"):
                item["conflict"] = {key: value for key, value in item["conflict"].items() if key != "customer"}
            if item.get("building") != SECOND_BUILDING_NAME:
                item["conflict"] = {"title": "Занято"} if item.get("conflict") else None
                item["nearest_booking"] = None
                item["pending_requests"] = []
            pending_count = len(item.get("pending_requests") or [])
            item["pending_request_count"] = pending_count
            item["pending_requests"] = [{"status": "pending"} for _ in range(pending_count)]
            safe[group].append(item)
    return safe


@app.post("/api/admin/availability")
def admin_availability(payload: AvailabilityRequest, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    validate_booking_window(payload.date, payload.time_start, payload.time_end)
    return build_availability(db, payload)


@app.post("/api/availability")
def user_availability(payload: AvailabilityRequest, user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    return _user_availability_view(admin_availability(payload, user, db))


@app.post("/api/admin/phone-bookings", status_code=201)
def create_phone_booking(payload: PhoneBookingCreate, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    require_request_details(payload, user)
    base = BookingCreate(**payload.model_dump(include=set(BookingCreate.model_fields)))
    by_phone = payload.external_channel in (None, "", "phone")
    if base.external_channel in ("phone", "service"): base.external_channel = None
    item = create_booking_service(db, base, user, source="phone" if by_phone else "admin_direct", customer_name=payload.customer_name.strip(),
                                  customer_contact=payload.customer_contact.strip() if payload.customer_contact else None,
                                  participants=payload.participants)
    return booking_to_dict(item)


@app.post("/api/admin/booking-series", status_code=201)
def create_booking_series(payload: BatchBookingCreate, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    require_request_details(payload, user)
    items = create_series(db, payload, user)
    return {"series_id": items[0].series_id if items else None, "created": len(items), "booking_ids": [item.id for item in items]}


@app.post("/api/booking-series", status_code=201)
def create_series_without_file(payload: BatchBookingCreate, user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(422, "Перед отправкой серии прикрепите файл")
    return create_user_booking_series(payload, user, db)


def create_user_booking_series(payload: BatchBookingCreate, user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    require_request_details(payload, user)
    items = create_series(db, payload, user, status="pending", source="self_service")
    return {"series_id": items[0].series_id if items else None, "created": len(items), "booking_ids": [item.id for item in items]}


@app.post("/api/booking-series/availability")
def booking_series_availability(payload: SeriesAvailabilityRequest, _: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    return series_conflicts(db, payload)


@app.post("/api/admin/booking-series/{series_id}/status")
def set_series_status(series_id: str, payload: SeriesStatusRequest, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return {"ok": True, "updated": transition_series_status(db, series_id, user, payload.status, payload.reason,
                                                            payload.skip_conflicts)}


@app.post("/api/admin/booking-series/{series_id}/cancel")
def cancel_admin_series(series_id: str, payload: BookingCancelRequest, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    count = cancel_series_records(db, series_id, user, reason=payload.reason, comment=payload.comment,
                                  replacement_offered=payload.replacement_offered, notify_customer=payload.notify_customer)
    return {"ok": True, "cancelled": count}


@app.get("/api/admin/service-blocks")
def list_blocks(_: User = Depends(admin_read_user), db: Session = Depends(get_db)):
    stmt = select(Booking).options(joinedload(Booking.room).joinedload(Room.building)).where(
        Booking.record_kind.in_(("maintenance", "setup", "teardown", "unavailable"))
    ).order_by(Booking.date.desc(), Booking.time_start, Booking.id)
    return [{"id": item.id, "title": item.title, "date": item.date.isoformat(),
             "room_number": item.room.number, "building": item.room.building.name,
             "time_start": item.time_start.strftime("%H:%M"), "time_end": item.time_end.strftime("%H:%M"),
             "record_kind": item.record_kind, "status": item.status} for item in db.scalars(stmt)]


@app.post("/api/admin/service-blocks", status_code=201)
def create_blocks(payload: ServiceBlockCreate, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    items = create_service_blocks(db, payload, user)
    return {"series_id": items[0].series_id if items else None, "created": len(items), "booking_ids": [item.id for item in items]}


@app.get("/api/admin/analytics")
def admin_analytics(date_from: date, date_to: date, _: User = Depends(admin_read_user), db: Session = Depends(get_db)):
    return build_analytics(db, date_from, date_to)


@app.post("/api/admin/buildings", status_code=201)
def create_building(payload: BuildingCreate, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    if db.scalar(select(Building.id).where(Building.name == payload.name.strip())): raise HTTPException(409, "Корпус уже существует")
    item = Building(name=payload.name.strip(), address=payload.address); db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "name": item.name, "address": item.address}

@app.post("/api/admin/rooms", status_code=201)
def create_room(payload: RoomCreate, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    if not db.get(Building, payload.building_id): raise HTTPException(404, "Корпус не найден")
    exists = db.scalar(select(Room.id).where(Room.building_id == payload.building_id, Room.number == payload.number.strip()))
    if exists: raise HTTPException(409, "Такая аудитория уже существует в корпусе")
    item = Room(**payload.model_dump()); item.number=item.number.strip(); item.name=item.name.strip(); db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id}

@app.put("/api/admin/rooms/{room_id}")
def update_room(room_id: int, payload: RoomCreate, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    item = db.get(Room, room_id)
    if not item: raise HTTPException(404, "Аудитория не найдена")
    data = payload.model_dump()
    if "max_capacity" not in payload.model_fields_set: data.pop("max_capacity")  # forms that don't know the field keep it
    # Same checks as creation: a wrong building or a duplicate number used to end in a 500.
    if not db.get(Building, payload.building_id): raise HTTPException(404, "Корпус не найден")
    duplicate = db.scalar(select(Room.id).where(Room.building_id == payload.building_id, Room.number == payload.number,
                                                Room.id != room_id))
    if duplicate: raise HTTPException(409, "Такая аудитория уже существует в корпусе")
    # Lowering the capacity must not leave accepted bookings that no longer fit.
    new_limit = max(data.get("max_capacity", item.max_capacity) or 0, payload.capacity)
    too_big = list(db.scalars(select(Booking).where(
        Booking.room_id == room_id, Booking.status.in_(("pending", "approved")), Booking.date >= local_today(),
        Booking.participants > new_limit,
    ).order_by(Booking.date, Booking.time_start).limit(9)))
    if too_big:
        listed = "; ".join(f"{booking.date:%d.%m.%Y} «{booking.title}» — {booking.participants} чел." for booking in too_big[:8])
        more = " и другие" if len(too_big) > 8 else ""
        raise HTTPException(409, f"Новая вместимость ({new_limit}) меньше числа участников будущих броней: {listed}{more}. Сначала перенесите их")
    for key,value in data.items(): setattr(item,key,value)
    db.commit(); return {"ok": True}

@app.delete("/api/admin/rooms/{room_id}")
def deactivate_room(room_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    item = db.get(Room, room_id)
    if not item: raise HTTPException(404, "Аудитория не найдена")
    # Switching a room off must not silently strand people who already booked it.
    upcoming = list(db.scalars(select(Booking).where(
        Booking.room_id == room_id, Booking.status.in_(("pending", "approved")), Booking.date >= local_today(),
    ).order_by(Booking.date, Booking.time_start).limit(9)))
    if upcoming:
        listed = "; ".join(f"{booking.date:%d.%m.%Y} {booking.time_start:%H:%M} «{booking.title}»" for booking in upcoming[:8])
        more = " и другие" if len(upcoming) > 8 else ""
        raise HTTPException(409, f"В аудитории есть будущие бронирования и заявки: {listed}{more}. Перенесите или отмените их, затем отключите аудиторию")
    item.is_active=False; db.commit(); return {"ok": True}
