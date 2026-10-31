from contextlib import asynccontextmanager
import asyncio
from collections import defaultdict
from datetime import date, datetime, time, timedelta
import logging
from pathlib import Path
import uuid
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import String, and_, cast, func, or_, select, text
from sqlalchemy.orm import Session, joinedload, selectinload
from .config import settings
from .database import SessionLocal, get_db
from .models import Booking, BookingComment, BookingEvent, Building, Department, DepartmentCurator, Room, User
from .schemas import (AvailabilityRequest, BookingArchiveRequest, BookingBulkArchiveRequest, BookingBulkRequest, BookingCancelRequest, BookingCreate, BookingStatusRequest,
                      BookingUpdate, BatchBookingCreate, ExtraRoomsAdd, BookingCommentCreate, BookingCommentResolve,
                      BookingTransferRequest, BuildingCreate, DepartmentCreate, EmailCodeRequest, LoginRequest, PasswordChangeRequest,
                      PasswordResetRequest, PhoneBookingCreate,
                      ProfileUpdate, RegisterRequest, RejectRequest, RoomCreate, SeriesAvailabilityRequest,
                      SeriesStatusRequest, ServiceBlockCreate)
from .security import (COOKIE_NAME, admin_read_user, admin_user, create_session, csrf_protected, current_user, hash_password,
                       set_session_cookie, verify_password)
from .serializers import booking_to_dict, calendar_booking_to_dict, room_to_dict
from .services.booking_locks import lock_booking_record
from .services.bookings import (BLOCKING_STATUSES, capacity_limit, check_capacity, create_booking as create_booking_service, find_conflict,
                                record_event, reject_competing_requests, validate_booking_window)
from .timeutils import local_now, local_today, utc_now
from .services.bookings import validate_booking_lead_time
from .services.availability import build_availability, equipment_categories as _equipment_categories
from .services.booking_lifecycle import (CLOSED_BOOKING_STATUSES, cancel_booking_record, cancel_series_records, delete_booking_record,
                                         delete_booking_records, set_bookings_archived,
                                         get_booking_or_404, set_booking_archived,
                                         transition_booking_status, transition_series_status)
from .services.operations import create_series, create_service_blocks, series_conflicts, transfer_booking
from .services.analytics import build_analytics
from .services.auth import (PURPOSE_REGISTER, PURPOSE_RESET, clear_login_failures, client_ip, consume_code, ensure_account_unlocked,
                            ensure_corporate_email, ensure_ip_allowed, ensure_password, issue_code, normalize_email,
                            record_login_failure, user_by_email, utcnow as auth_now)
from .services.lifecycle_worker import lifecycle_loop
from .services.room_sets import create_extra_rooms, extra_rooms_of, move_extra_rooms
from .services.attachments import (MAX_FILE_BYTES, add_attachments, delete_attachment, get_attachment_for, inline_allowed,
                                   remove_unused_files, save_attachment, stored_names_of)




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
UPLOAD_DIR = Path(__file__).resolve().parents[1] / "uploads" / "avatars"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
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

@app.post("/api/auth/register/request-code")
def request_registration_code(payload: EmailCodeRequest, request: Request, db: Session = Depends(get_db)):
    email = normalize_email(payload.email)
    ensure_corporate_email(email)
    if user_by_email(db, email): raise HTTPException(409, "Этот адрес уже зарегистрирован. Войдите или восстановите пароль")
    issue_code(db, email, PURPOSE_REGISTER, client_ip(request))
    return {"ok": True, "email": email, "ttl_minutes": settings.email_code_ttl_minutes,
            "resend_seconds": settings.email_code_resend_seconds}

@app.post("/api/auth/register", status_code=201)
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    email = normalize_email(payload.email)
    ensure_corporate_email(email)
    ensure_password(payload.password, email)
    if user_by_email(db, email): raise HTTPException(409, "Этот адрес уже зарегистрирован. Войдите или восстановите пароль")
    consume_code(db, email, PURPOSE_REGISTER, payload.code)
    now = auth_now()
    user = User(email=email, full_name=payload.full_name, department=payload.department, phone=payload.phone, password_hash=hash_password(payload.password),
                email_verified_at=now, password_changed_at=now)
    db.add(user); db.commit(); db.refresh(user)
    token, csrf = create_session(user); set_session_cookie(response, token)
    return {"user": user_json(user), "csrf_token": csrf}

@app.post("/api/auth/login")
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    email = normalize_email(payload.email); ip = client_ip(request)
    ensure_ip_allowed(ip)
    user = user_by_email(db, email)
    ensure_account_unlocked(user, email)
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        record_login_failure(db, user, email, ip)
        raise HTTPException(401, "Неверный email или пароль")
    clear_login_failures(user); db.commit()
    token, csrf = create_session(user); set_session_cookie(response, token)
    return {"user": user_json(user), "csrf_token": csrf}

@app.post("/api/auth/password/forgot")
def forgot_password(payload: EmailCodeRequest, request: Request, db: Session = Depends(get_db)):
    email = normalize_email(payload.email)
    user = user_by_email(db, email)
    # The answer is the same whether or not the address is registered.
    if user and user.is_active: issue_code(db, email, PURPOSE_RESET, client_ip(request))
    return {"ok": True, "email": email, "ttl_minutes": settings.email_code_ttl_minutes,
            "resend_seconds": settings.email_code_resend_seconds}

@app.post("/api/auth/password/reset")
def reset_password(payload: PasswordResetRequest, response: Response, db: Session = Depends(get_db)):
    email = normalize_email(payload.email)
    ensure_password(payload.password, email)
    user = user_by_email(db, email)
    consume_code(db, email, PURPOSE_RESET, payload.code)
    if not user or not user.is_active: raise HTTPException(400, "Код устарел или не запрашивался. Запросите новый код")
    set_new_password(user, payload.password)
    # Receiving the code proves the mailbox belongs to the user.
    user.email_verified_at = user.email_verified_at or auth_now()
    db.commit(); db.refresh(user)
    token, csrf = create_session(user); set_session_cookie(response, token)
    return {"user": user_json(user), "csrf_token": csrf}

@app.post("/api/auth/password/change")
def change_password(payload: PasswordChangeRequest, response: Response, user: User = Depends(csrf_protected),
                    db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, user.password_hash): raise HTTPException(400, "Текущий пароль указан неверно")
    ensure_password(payload.password, user.email)
    if verify_password(payload.password, user.password_hash): raise HTTPException(400, "Новый пароль совпадает с текущим")
    set_new_password(user, payload.password)
    db.commit(); db.refresh(user)
    # Other devices are signed out; this one gets a fresh session.
    token, csrf = create_session(user); set_session_cookie(response, token)
    return {"user": user_json(user), "csrf_token": csrf}

def set_new_password(user: User, password: str):
    user.password_hash = hash_password(password); user.password_changed_at = auth_now()
    user.session_version = (user.session_version or 0) + 1
    clear_login_failures(user)

@app.post("/api/auth/logout")
def logout(response: Response, _: User = Depends(csrf_protected)):
    response.delete_cookie(COOKIE_NAME, path="/"); return {"ok": True}

@app.get("/api/auth/me")
def me(request: Request, user: User = Depends(current_user)):
    from .security import decode_session
    return {"user": user_json(user), "csrf_token": decode_session(request.cookies[COOKIE_NAME])["csrf"]}

def user_json(user: User): return {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role,
                                  "position": user.position, "phone": user.phone, "department": user.department,
                                  "avatar_url": user.avatar_url, "created_at": user.created_at.isoformat() if user.created_at else None}

@app.get("/api/profile/extra-rooms-guide")
def extra_rooms_guide_status(user: User = Depends(current_user)):
    return {"seen": user.extra_rooms_guide_seen}


@app.post("/api/profile/extra-rooms-guide/seen")
def mark_extra_rooms_guide_seen(user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    user.extra_rooms_guide_seen = True
    db.commit()
    return {"seen": True}


@app.put("/api/profile")
def update_profile(payload: ProfileUpdate, user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    old_name = user.full_name
    user.full_name = payload.full_name.strip(); user.position = payload.position or None
    user.phone = payload.phone or None; user.department = payload.department or None
    # Past and closed records keep the name they were created with.
    for booking in db.scalars(select(Booking).where(Booking.owner_id == user.id, Booking.date >= local_today(),
                                                    Booking.status.in_(("pending", "approved")))):
        booking.booked_by = user.full_name
        # The responsible person defaults to the requester; a different person typed by hand stays.
        if booking.customer_name == old_name:
            booking.customer_name = user.full_name
    db.commit(); db.refresh(user)
    return {"user": user_json(user)}

AVATAR_MAX_BYTES = 5 * 1024 * 1024
IMAGE_SIGNATURES = {"image/jpeg": (b"\xff\xd8\xff",), "image/png": (b"\x89PNG\r\n\x1a\n",), "image/webp": (b"RIFF",)}


@app.post("/api/profile/avatar")
async def upload_avatar(request: Request, user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    content_type = request.headers.get("content-type", "").split(";")[0]
    extensions = {"image/jpeg":"jpg", "image/png":"png", "image/webp":"webp"}
    if content_type not in extensions: raise HTTPException(415, "Разрешены JPG, PNG и WEBP")
    content = await _read_limited(request, AVATAR_MAX_BYTES, "Размер изображения должен быть не более 5 МБ")
    if not content: raise HTTPException(413, "Размер изображения должен быть не более 5 МБ")
    # The declared type is only a header; check the file really is that kind of image.
    if not any(content.startswith(magic) for magic in IMAGE_SIGNATURES[content_type]) or (
            content_type == "image/webp" and content[8:12] != b"WEBP"):
        raise HTTPException(415, "Файл не похож на изображение JPG, PNG или WEBP")
    if user.avatar_url:
        old = UPLOAD_DIR / Path(user.avatar_url).name
        if old.exists(): old.unlink()
    filename = f"{user.id}-{uuid.uuid4().hex}.{extensions[content_type]}"
    (UPLOAD_DIR / filename).write_bytes(content)
    user.avatar_url = f"/api/uploads/avatars/{filename}"; db.commit(); db.refresh(user)
    return {"user": user_json(user)}

@app.delete("/api/profile/avatar")
def delete_avatar(user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    if user.avatar_url:
        old = UPLOAD_DIR / Path(user.avatar_url).name
        if old.exists(): old.unlink()
    user.avatar_url = None; db.commit(); db.refresh(user)
    return {"user": user_json(user)}


@app.get("/api/buildings")
def buildings(db: Session = Depends(get_db)):
    return [{"id": b.id, "name": b.name, "address": b.address, "image": b.image, "color": b.color} for b in db.scalars(select(Building).order_by(Building.id))]


@app.get("/api/departments")
def departments(_: User = Depends(current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(Department).options(selectinload(Department.curators)).where(Department.is_active).order_by(Department.code))
    return [{"id": item.id, "code": item.code, "name": item.name,
             "curators": [{"id": curator.id, "full_name": curator.full_name, "contact": curator.contact} for curator in item.curators]}
            for item in items]


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
    remaining = db.scalars(select(Booking).where(
        Booking.date == now.date(), Booking.status == "approved", Booking.time_end > current,
    ).order_by(Booking.room_id, Booking.time_start, Booking.time_end))
    by_room: dict[int, list[Booking]] = defaultdict(list)
    for item in remaining:
        by_room[item.room_id].append(item)
    result = {}
    for room_id, records in by_room.items():
        first = records[0]
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


# The month grid asks for six weeks; a longer range is either a bug or a scraping attempt.
CALENDAR_MAX_DAYS = 62


@app.get("/api/bookings")
def bookings(date_from: date, date_to: date, room_id: int | None = None,
             user: User = Depends(current_user), db: Session = Depends(get_db)):
    # Bookings that already took place stay on the calendar as part of the room history.
    visibility = Booking.status.in_(("approved", "completed"))
    if date_to < date_from:
        raise HTTPException(400, "Дата окончания периода раньше даты начала")
    if (date_to - date_from).days > CALENDAR_MAX_DAYS:
        raise HTTPException(400, f"Календарь загружается периодами не длиннее {CALENDAR_MAX_DAYS} дней")
    stmt = select(Booking).options(
        joinedload(Booking.room).joinedload(Room.building), joinedload(Booking.owner), joinedload(Booking.department),
        joinedload(Booking.decided_by), joinedload(Booking.cancelled_by), joinedload(Booking.archived_by),
    ).where(Booking.date >= date_from, Booking.date <= date_to, visibility)
    if room_id: stmt = stmt.where(Booking.room_id == room_id)
    return [calendar_booking_to_dict(item, include_private=user.role == "admin", include_reference=item.owner_id == user.id)
            for item in db.scalars(stmt.order_by(Booking.date, Booking.time_start))]


@app.post("/api/bookings", status_code=201)
def create_booking(payload: BookingCreate, user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    require_request_details(payload, user)
    return booking_to_dict(create_booking_service(db, payload, user))


def require_request_details(payload: BookingCreate | BatchBookingCreate, user: User) -> None:
    """Validate new bookings for both roles without modifying historical records."""
    missing = [label for label, present in (
        ("количество участников", payload.participants),
        ("ФИО ответственного", len((payload.customer_name or "").strip()) >= 2),
        ("подразделение", payload.department_id or payload.department_name),
        ("номер заявки", (payload.external_reference or "").strip()),
    ) if not present]
    if missing:
        raise HTTPException(422, "Заполните обязательные поля: " + ", ".join(missing))

@app.get("/api/me/bookings")
def my_bookings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Booking).options(joinedload(Booking.room).joinedload(Room.building), joinedload(Booking.owner),
                                   joinedload(Booking.cancelled_by), joinedload(Booking.archived_by),
                                   joinedload(Booking.decided_by)).where(Booking.owner_id == user.id).order_by(Booking.date.desc(), Booking.time_start)
    items = list(db.scalars(stmt))
    return add_attachments(db, items, [booking_to_dict(item) for item in items])

@app.post("/api/me/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: int, payload: BookingCancelRequest, user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    item = get_booking_or_404(db, booking_id)
    if item.owner_id != user.id and user.role != "admin":
        raise HTTPException(404, "Бронирование не найдено")
    cancel_booking_record(db, item, user, reason=payload.reason, comment=payload.comment,
                          replacement_offered=payload.replacement_offered,
                          notify_customer=payload.notify_customer)
    return {"ok": True}


@app.post("/api/me/booking-series/{series_id}/cancel")
def cancel_my_series(series_id: str, payload: BookingCancelRequest, user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    count = cancel_series_records(db, series_id, user, reason=payload.reason, comment=payload.comment,
                                  replacement_offered=payload.replacement_offered, notify_customer=payload.notify_customer)
    return {"ok": True, "cancelled": count}


def _add_extra_rooms(db: Session, main: Booking, payload: ExtraRoomsAdd, actor: User, status: str | None) -> list[dict]:
    try:
        items = create_extra_rooms(db, main, payload.extra_rooms, actor, status=status)
        db.commit()
    except Exception:
        db.rollback(); raise
    return [booking_to_dict(db.get(Booking, item.id)) for item in items]


@app.post("/api/me/bookings/{booking_id}/extra-rooms", status_code=201)
def add_my_extra_rooms(booking_id: int, payload: ExtraRoomsAdd, user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    main = get_booking_or_404(db, booking_id)
    if main.owner_id != user.id and user.role != "admin":
        raise HTTPException(404, "Бронирование не найдено")
    # A user's addition is a request even when the main booking is already approved.
    return _add_extra_rooms(db, main, payload, user, "approved" if user.role == "admin" and main.status == "approved" else "pending")


@app.post("/api/admin/booking-center/{booking_id}/extra-rooms", status_code=201)
def add_admin_extra_rooms(booking_id: int, payload: ExtraRoomsAdd, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return _add_extra_rooms(db, get_booking_or_404(db, booking_id), payload, user, None)


NOTIFICATION_EVENTS = ("approved", "rejected", "expired", "cancelled_by_admin", "transferred", "updated")


async def _read_limited(request: Request, limit: int, message: str) -> bytes:
    """Read the body but stop as soon as it grows past the limit.

    Content-Length is optional (chunked uploads) and can lie, so it is only a
    quick early rejection; the running total is what actually protects memory.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, message)
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, message)
        chunks.append(chunk)
    return b"".join(chunks)


async def _read_upload(request: Request) -> bytes:
    return await _read_limited(request, MAX_FILE_BYTES, "Размер файла должен быть не более 20 МБ")


@app.post("/api/bookings/{booking_id}/attachments", status_code=201)
async def upload_booking_attachment(booking_id: int, request: Request, user: User = Depends(csrf_protected),
                                    db: Session = Depends(get_db)):
    content = await _read_upload(request)
    return save_attachment(db, user, content, request.headers.get("x-file-name"), booking_id=booking_id)


@app.post("/api/booking-series/{series_id}/attachments", status_code=201)
async def upload_series_attachment(series_id: str, request: Request, user: User = Depends(csrf_protected),
                                   db: Session = Depends(get_db)):
    content = await _read_upload(request)
    return save_attachment(db, user, content, request.headers.get("x-file-name"), series_id=series_id)


@app.get("/api/attachments/{attachment_id}")
def open_attachment(attachment_id: int, download: bool = False, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    item, path = get_attachment_for(db, user, attachment_id)
    inline = inline_allowed(item) and not download
    # PDFs need the browser's built-in viewer, which a strict policy would block; other files never run anything.
    headers = {} if inline and item.content_type == "application/pdf" else {
        "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"}
    return FileResponse(path, media_type=item.content_type, filename=item.original_name,
                        content_disposition_type="inline" if inline else "attachment", headers=headers)


@app.delete("/api/attachments/{attachment_id}")
def remove_attachment(attachment_id: int, user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    delete_attachment(db, user, attachment_id)
    return {"ok": True}


@app.get("/api/me/notifications")
def my_notifications(after: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Decisions other people (or the system) made about the user's bookings.

    The first call (after=0) only needs the latest events. Later calls return
    everything after the cursor in order, page by page, so nothing is skipped
    when many events arrive at once. One decision on a whole series becomes a
    single notification.
    """
    stmt = select(BookingEvent).join(Booking, BookingEvent.booking_id == Booking.id).options(
        joinedload(BookingEvent.booking).joinedload(Booking.room).joinedload(Room.building),
    ).where(
        Booking.owner_id == user.id, BookingEvent.id > after, BookingEvent.event_type.in_(NOTIFICATION_EVENTS),
        or_(BookingEvent.actor_id != user.id, BookingEvent.event_type == "expired"),
        # The administrator chose "do not notify the customer" for this cancellation or transfer.
        # (PostgreSQL returns JSON false as "false", SQLite as 0.)
        func.coalesce(cast(BookingEvent.data["notify_customer"].as_string(), String), "true").not_in(("false", "0")),
    )
    if after:
        items = list(db.scalars(stmt.order_by(BookingEvent.id).limit(500)))
    else:
        items = list(reversed(list(db.scalars(stmt.order_by(BookingEvent.id.desc()).limit(30)))))
    result = []
    for event in items:
        booking = event.booking
        series_id = (event.data or {}).get("series_id") or ((f"set-{event.data['set_id']}") if (event.data or {}).get("set_id") else None)
        last = result[-1] if result else None
        if (series_id and last and last["series_id"] == series_id and last["type"] == event.event_type
                and last["reason"] == (event.data or {}).get("reason")):
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
            "reason": (event.data or {}).get("reason"), "series_id": series_id, "series_count": 1,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        })
    for entry in result:
        if entry["series_count"] > 1 and str(entry["series_id"]).startswith("set-"):
            entry["summary"] = f"{entry['summary']} — комплект, аудиторий: {entry['series_count']}"
        elif entry["series_count"] > 1:
            entry["summary"] = f"{entry['summary']} — серия, дат: {entry['series_count']}"
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
            pending_count = len(item.get("pending_requests") or [])
            item["pending_request_count"] = pending_count
            item["pending_requests"] = [{"status": "pending"} for _ in range(pending_count)]
            safe[group].append(item)
    return safe


@app.get("/api/booking-policy")
def booking_policy(booking_date: date, user: User = Depends(current_user)):
    validate_booking_lead_time(booking_date)
    return {"valid": True}


@app.post("/api/admin/availability")
def admin_availability(payload: AvailabilityRequest, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    validate_booking_lead_time(payload.date)
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


@app.post("/api/admin/service-blocks", status_code=201)
def create_blocks(payload: ServiceBlockCreate, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    items = create_service_blocks(db, payload, user)
    return {"series_id": items[0].series_id if items else None, "created": len(items), "booking_ids": [item.id for item in items]}


@app.get("/api/admin/analytics")
def admin_analytics(date_from: date, date_to: date, _: User = Depends(admin_read_user), db: Session = Depends(get_db)):
    return build_analytics(db, date_from, date_to)


@app.get("/api/admin/booking-center")
def booking_center(scope: str = "all", user: User = Depends(admin_read_user), db: Session = Depends(get_db)):
    stmt = select(Booking).options(joinedload(Booking.room).joinedload(Room.building), joinedload(Booking.owner),
                                   joinedload(Booking.cancelled_by), joinedload(Booking.archived_by), joinedload(Booking.department),
                                   joinedload(Booking.decided_by))
    if scope == "mine": stmt = stmt.where(Booking.owner_id == user.id)
    elif scope != "all": raise HTTPException(400, "Неизвестная область просмотра")
    items = list(db.scalars(stmt.order_by(Booking.date.desc(), Booking.time_start.desc())))
    # Conflicts of all open records in one query instead of one query per record.
    open_items = [item for item in items if item.status in {"pending", "approved"}]
    occupied: dict[tuple[int, date], list[tuple[int, object, object]]] = {}
    if open_items:
        rows = db.execute(select(Booking.id, Booking.room_id, Booking.date, Booking.time_start, Booking.time_end).where(
            Booking.status.in_(BLOCKING_STATUSES), Booking.room_id.in_(list({item.room_id for item in open_items})),
            Booking.date >= min(item.date for item in open_items), Booking.date <= max(item.date for item in open_items)))
        for booking_id, room_id, day, start, end in rows:
            occupied.setdefault((room_id, day), []).append((booking_id, start, end))
    result = []
    for item in items:
        data = booking_to_dict(item)
        data["has_conflict"] = item.status in {"pending", "approved"} and any(
            other_id != item.id and start < item.time_end and end > item.time_start
            for other_id, start, end in occupied.get((item.room_id, item.date), []))
        result.append(data)
    return add_attachments(db, items, result)


@app.get("/api/admin/booking-center/{booking_id}")
def booking_center_detail(booking_id: int, _: User = Depends(admin_read_user), db: Session = Depends(get_db)):
    stmt = select(Booking).options(
        joinedload(Booking.room).joinedload(Room.building), joinedload(Booking.owner), joinedload(Booking.cancelled_by),
        joinedload(Booking.archived_by), joinedload(Booking.department),
        selectinload(Booking.events).joinedload(BookingEvent.actor),
        selectinload(Booking.comments).joinedload(BookingComment.author),
        selectinload(Booking.comments).joinedload(BookingComment.resolved_by),
    ).where(Booking.id == booking_id)
    item = db.scalars(stmt).unique().one_or_none()
    if not item: raise HTTPException(404, "Бронирование не найдено")
    data = add_attachments(db, [item], [booking_to_dict(item, include_events=True)])[0]
    data["extra_rooms"] = [booking_to_dict(extra) for extra in extra_rooms_of(db, item)] if not item.parent_booking_id else []
    parent = db.get(Booking, item.parent_booking_id) if item.parent_booking_id else None
    data["parent"] = {"id": parent.id, "title": parent.title, "room_number": parent.room.number, "status": parent.status} if parent else None
    conflict = find_conflict(db, item.room_id, item.date, item.time_start, item.time_end, item.id)
    data["assessment"] = {
        "available": conflict is None,
        "message": "Аудитория свободна, пересечений нет" if conflict is None else
                   f"Обнаружено пересечение с бронью {conflict.time_start.strftime('%H:%M')}–{conflict.time_end.strftime('%H:%M')}",
        "capacity_ok": not item.participants or capacity_limit(item.room) >= item.participants,
        # Fits only with extra seating (between the regular and the maximum capacity).
        "over_capacity": bool(item.participants and item.participants > item.room.capacity),
    }
    if data["assessment"]["capacity_ok"] and data["assessment"]["over_capacity"]:
        data["assessment"]["message"] += f". Участников больше обычной вместимости ({item.room.capacity}) — понадобятся дополнительные места"
    elif not data["assessment"]["capacity_ok"]:
        data["assessment"]["message"] += f". Участников больше, чем вмещает аудитория ({capacity_limit(item.room)})"
    return data


@app.post("/api/admin/booking-center/{booking_id}/transfer", status_code=201)
def transfer_admin_booking(booking_id: int, payload: BookingTransferRequest, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    original = get_booking_or_404(db, booking_id)
    return booking_to_dict(transfer_booking(db, original, payload, user))


@app.post("/api/admin/booking-center/{booking_id}/comments", status_code=201)
def add_booking_comment(booking_id: int, payload: BookingCommentCreate, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    booking = get_booking_or_404(db, booking_id)
    item = BookingComment(booking_id=booking.id, author_id=user.id, text=payload.text.strip())
    db.add(item); db.flush()
    record_event(db, booking, user, "comment_added", "Добавлен рабочий комментарий", {"comment_id": item.id})
    db.commit(); db.refresh(item)
    return {"id": item.id, "text": item.text, "author": user.full_name, "created_at": item.created_at.isoformat(), "resolved_at": None}


@app.post("/api/admin/booking-center/{booking_id}/comments/{comment_id}/resolve")
def resolve_booking_comment(booking_id: int, comment_id: int, payload: BookingCommentResolve,
                            user: User = Depends(admin_user), db: Session = Depends(get_db)):
    item = db.scalar(select(BookingComment).where(BookingComment.id == comment_id, BookingComment.booking_id == booking_id))
    if not item: raise HTTPException(404, "Комментарий не найден")
    item.resolved_at = utc_now() if payload.resolved else None
    item.resolved_by_id = user.id if payload.resolved else None
    record_event(db, item.booking, user, "comment_resolved" if payload.resolved else "comment_reopened",
                 "Рабочий вопрос закрыт" if payload.resolved else "Рабочий вопрос открыт повторно", {"comment_id": item.id})
    db.commit()
    return {"ok": True}


def _history_value(value):
    if isinstance(value, time): return value.strftime("%H:%M")
    if isinstance(value, (date, datetime)): return value.isoformat()
    return value


@app.put("/api/admin/booking-center/{booking_id}")
def update_admin_booking(booking_id: int, payload: BookingUpdate, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    item = db.get(Booking, booking_id)
    if not item: raise HTTPException(404, "Бронирование не найдено")
    item = lock_booking_record(db, item)
    if item.status in CLOSED_BOOKING_STATUSES:
        raise HTTPException(409, "Закрытое бронирование нельзя изменять")
    values = payload.model_dump(exclude_unset=True)
    room_id = values.get("room_id", item.room_id); booking_date = values.get("date", item.date)
    start = values.get("time_start", item.time_start); end = values.get("time_end", item.time_end)
    schedule_changed = (room_id, booking_date, start, end) != (item.room_id, item.date, item.time_start, item.time_end)
    if item.parent_booking_id and booking_date != item.date:
        raise HTTPException(409, "Дополнительная аудитория бронируется на день основной брони — перенесите основную бронь")
    set_extras = [] if item.parent_booking_id else extra_rooms_of(db, item, open_only=True)
    if booking_date != item.date or room_id != item.room_id:
        validate_booking_lead_time(booking_date)
    if schedule_changed: validate_booking_window(booking_date, start, end)
    target_room = db.get(Room, room_id)
    if not target_room:
        raise HTTPException(404, "Аудитория не найдена")
    # A booking already standing in a room that was switched off stays editable
    # (title, contacts, cancellation details); only moving into such a room is refused.
    if not target_room.is_active and (room_id != item.room_id or schedule_changed):
        raise HTTPException(409, "Аудитория отключена — выберите другую аудиторию")
    if values.get("department_id") is not None and not db.get(Department, values["department_id"]):
        raise HTTPException(404, "Подразделение не найдено")
    participants = values.get("participants") or item.participants
    if room_id != item.room_id or participants != item.participants: check_capacity(target_room, participants)
    lock_key = booking_date.toordinal() * 100000 + room_id
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    conflict = find_conflict(db, room_id, booking_date, start, end, item.id)
    if conflict: raise HTTPException(409, "Выбранная аудитория занята в это время")
    before = {"room_id": item.room_id, "date": item.date.isoformat(), "time_start": item.time_start.strftime("%H:%M"),
              "time_end": item.time_end.strftime("%H:%M"), "title": item.title}
    # Every field that really changed keeps its previous value (phone, participants,
    # department, equipment...), not only the schedule, so a dispute can be traced.
    changes = {key: {"before": _history_value(getattr(item, key)), "after": _history_value(value)}
               for key, value in values.items() if getattr(item, key) != value}
    for key, value in values.items(): setattr(item, key, value)
    item.updated_at = utc_now()
    after = {"room_id": item.room_id, "date": item.date.isoformat(), "time_start": item.time_start.strftime("%H:%M"),
             "time_end": item.time_end.strftime("%H:%M"), "title": item.title}
    record_event(db, item, user, "updated", "Параметры бронирования изменены",
                 {"before": before, "after": after, "changes": changes})
    if set_extras and schedule_changed:
        move_extra_rooms(db, set_extras, item, user)
    if item.status == "approved" and schedule_changed:
        reject_competing_requests(db, item, user)
    db.commit()
    return {"ok": True}


@app.post("/api/admin/booking-center/{booking_id}/archive")
def archive_admin_booking(booking_id: int, payload: BookingArchiveRequest, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    item = get_booking_or_404(db, booking_id)
    set_booking_archived(db, item, user, payload.archived)
    return {"ok": True}


@app.post("/api/admin/booking-bulk/archive")
def archive_admin_bookings(payload: BookingBulkArchiveRequest, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return {"ok": True, "count": set_bookings_archived(db, payload.ids, user, payload.archived)}


@app.post("/api/admin/booking-bulk/delete")
def delete_admin_bookings(payload: BookingBulkRequest, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    remove_unused_files(db, delete_booking_records(db, payload.ids, user))
    return {"ok": True}


@app.post("/api/admin/booking-center/{booking_id}/cancel")
def cancel_admin_booking(booking_id: int, payload: BookingCancelRequest, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    item = get_booking_or_404(db, booking_id)
    cancel_booking_record(db, item, user, reason=payload.reason, comment=payload.comment,
                          replacement_offered=payload.replacement_offered,
                          notify_customer=payload.notify_customer)
    return {"ok": True}


@app.delete("/api/admin/booking-center/{booking_id}")
def delete_admin_booking(booking_id: int, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    item = get_booking_or_404(db, booking_id)
    # Same path as a series: extra rooms of a set go with the main record (with their files),
    # and a record that depends on one of them blocks the deletion with a clear 409.
    remove_unused_files(db, delete_booking_records(db, [item.id], user))
    return {"ok": True}


@app.post("/api/admin/booking-center/{booking_id}/status")
def set_booking_status(booking_id: int, payload: BookingStatusRequest, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    item = get_booking_or_404(db, booking_id)
    transition_booking_status(db, item, user, payload.status, payload.reason)
    return {"ok": True}

@app.get("/api/admin/bookings")
def moderation(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "admin": raise HTTPException(403, "Недостаточно прав")
    stmt = select(Booking).options(joinedload(Booking.room).joinedload(Room.building), joinedload(Booking.department)).where(Booking.status == "pending").order_by(Booking.created_at)
    result = []
    items = list(db.scalars(stmt))
    for item in items:
        data = booking_to_dict(item)
        conflict = find_conflict(db, item.room_id, item.date, item.time_start, item.time_end, item.id)
        data["has_conflict"] = conflict is not None
        if conflict:
            data["conflict"] = {"id": conflict.id, "title": conflict.title,
                                "time_start": conflict.time_start.strftime("%H:%M"),
                                "time_end": conflict.time_end.strftime("%H:%M")}
        result.append(data)
    for data in result:
        data["competing_requests"] = sum(
            1 for other in result if other["id"] != data["id"] and other["room_id"] == data["room_id"]
            and other["date"] == data["date"] and other["time_start"] < data["time_end"] and other["time_end"] > data["time_start"]
            and not (data["series_id"] and other["series_id"] == data["series_id"]))
    return add_attachments(db, items, result)

@app.post("/api/admin/bookings/{booking_id}/approve")
def approve(booking_id: int, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    item = db.get(Booking, booking_id)
    if not item or item.status != "pending": raise HTTPException(404, "Заявка не найдена")
    transition_booking_status(db, item, user, "approved")
    return {"ok": True}

@app.post("/api/admin/bookings/{booking_id}/reject")
def reject(booking_id: int, payload: RejectRequest, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    item = db.get(Booking, booking_id)
    if not item or item.status != "pending": raise HTTPException(404, "Заявка не найдена")
    transition_booking_status(db, item, user, "rejected", payload.reason)
    return {"ok": True}

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
