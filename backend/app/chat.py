import base64
import binascii
from datetime import timedelta
from threading import Lock
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Table, Text, func, or_, select, update
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import Booking, User
from .security import csrf_protected, current_user
from .timeutils import utc_now

router = APIRouter(prefix="/api/chat")
messages = Table(
    "chat_messages", Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("sender_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("recipient_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("thread", String(80), nullable=False),
    Column("body", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("read_at", DateTime(timezone=True)),
    Index("ix_chat_sender_thread", "sender_id", "thread", "id"),
    Index("ix_chat_recipient_thread", "recipient_id", "thread", "id"),
)


class MessageCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    body: str = Field(min_length=1, max_length=4000)


MAX_CHAT_FILE = 5 * 1024 * 1024
attachments = Table(
    "chat_attachments", Base.metadata,
    Column("message_id", ForeignKey("chat_messages.id", ondelete="CASCADE"), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("size", Integer, nullable=False),
    Column("content", LargeBinary, nullable=False),
)


class FileMessage(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=4000)
    content: str = Field(min_length=1, max_length=4 * ((MAX_CHAT_FILE + 2) // 3))


class TypingState(BaseModel):
    active: bool = True


PRESENCE_TTL = timedelta(seconds=18)
TYPING_TTL = timedelta(seconds=7)
_presence: dict[int, object] = {}
_typing: dict[tuple[str, int], object] = {}
_state_lock = Lock()


def touch(user_id: int) -> None:
    with _state_lock:
        _presence[user_id] = utc_now()


def online(user_id: int) -> bool:
    with _state_lock:
        seen = _presence.get(user_id)
    return bool(seen and utc_now() - seen <= PRESENCE_TTL)


def typing(key: str, user_id: int) -> bool:
    with _state_lock:
        expires = _typing.get((key, user_id))
        if expires and expires < utc_now():
            _typing.pop((key, user_id), None)
            return False
    return bool(expires)


def file_preview(name: str | None) -> str | None:
    extension = (name or "").rsplit(".", 1)[-1].lower()
    if extension in {"png", "jpg", "jpeg", "gif", "webp"}:
        return "image"
    if extension == "pdf":
        return "pdf"
    return None


def participants(target: str, user: User, db: Session):
    kind, _, value = target.partition(":")
    if kind == "person" and value.isascii() and value.isdecimal() and len(value) <= 10:
        peer = db.get(User, int(value)) if int(value) <= 2147483647 else None
        if peer and peer.is_active and peer.id != user.id:
            return f"person:{min(user.id, peer.id)}:{max(user.id, peer.id)}", peer.id, peer.full_name
    if kind in {"booking", "series"}:
        stmt = select(Booking).where(Booking.record_kind == "booking")
        if kind == "booking" and value.isascii() and value.isdecimal() and len(value) <= 10 and int(value) <= 2147483647:
            stmt = stmt.where(Booking.id == int(value))
        elif kind == "series" and len(value) <= 64:
            stmt = stmt.where(Booking.series_id == value, Booking.parent_booking_id.is_(None))
        else:
            raise HTTPException(404, "Чат не найден")
        if user.role != "admin":
            stmt = stmt.where(Booking.owner_id == user.id)
        booking = db.scalar(stmt.order_by(Booking.id).limit(1))
        if booking and booking.parent_booking_id:
            booking = db.get(Booking, booking.parent_booking_id)
        if booking and (user.role == "admin" or booking.owner_id == user.id):
            peer = db.get(User, booking.owner_id) if user.role == "admin" and booking.owner_id else db.scalar(
                select(User).where(User.role == "admin", User.is_active).limit(1))
            if peer and peer.is_active:
                key = f"series:{booking.series_id}" if booking.series_id else f"booking:{booking.id}"
                return key, peer.id, booking.title
    raise HTTPException(404, "Чат недоступен")


def visible(user_id):
    return or_(messages.c.sender_id == user_id, messages.c.recipient_id == user_id)


@router.get("/people")
def people(q: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    touch(user.id)
    q = q.strip()[:100]
    if not q:
        return []
    rows = db.execute(select(User.id, User.full_name, User.avatar_url).where(User.is_active, User.id != user.id,
                       User.full_name.icontains(q, autoescape=True)).order_by(User.full_name, User.id).limit(20))
    return [{"target": f"person:{row.id}", "title": row.full_name, "avatar_url": row.avatar_url,
             "online": online(row.id)} for row in rows]


@router.get("/inbox")
def inbox(user: User = Depends(current_user), db: Session = Depends(get_db)):
    touch(user.id)
    rows = db.execute(select(messages.c.thread, func.max(messages.c.id).label("latest"),
                      func.count().filter(messages.c.recipient_id == user.id, messages.c.sender_id != user.id, messages.c.read_at.is_(None)).label("unread"))
                      .where(visible(user.id)).group_by(messages.c.thread).order_by(func.max(messages.c.id).desc()))
    threads = []
    for row in rows:
        target = row.thread
        if target.startswith("person:"):
            _, a, b = target.split(":")
            target = f"person:{b if a == str(user.id) else a}"
        try:
            _, peer_id, title = participants(target, user, db)
        except HTTPException:
            continue
        last = db.execute(select(messages.c.sender_id, messages.c.read_at,
                                 func.substr(messages.c.body, 1, 145).label("preview"),
                                 attachments.c.name).select_from(messages.outerjoin(attachments))
                          .where(messages.c.id == row.latest)).one_or_none()
        peer = db.get(User, peer_id)
        threads.append({"target": target, "title": title, "unread": row.unread,
                        "peer_name": peer.full_name, "avatar_url": peer.avatar_url,
                        "online": online(peer_id), "typing": typing(row.thread, peer_id),
                        "last": {"mine": last.sender_id == user.id,
                                 "read": last.read_at is not None,
                                 "text": last.preview or last.name or ""} if last else None})
    return {"threads": threads, "unread": sum(item["unread"] for item in threads)}


@router.get("/thread/{target}")
def thread(target: str, before: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    touch(user.id)
    key, peer_id, title = participants(target, user, db)
    peer = db.get(User, peer_id)
    stmt = select(messages, attachments.c.name, attachments.c.size).select_from(messages.outerjoin(attachments)).where(
        messages.c.thread == key, visible(user.id))
    if before is not None:
        stmt = stmt.where(messages.c.id < before)
    rows = list(db.execute(stmt.order_by(messages.c.id.desc()).limit(51)).mappings())
    return {"title": title, "peer_name": peer.full_name, "avatar_url": peer.avatar_url,
            "online": online(peer_id), "typing": typing(key, peer_id), "more": len(rows) > 50, "messages": [
        {"id": row["id"], "mine": row["sender_id"] == user.id, "body": row["body"], "at": row["created_at"].isoformat(),
         "read": row["read_at"] is not None, "file": {"name": row["name"], "size": row["size"],
                                                    "preview": file_preview(row["name"]),
                                                    "url": f"/api/chat/thread/{key if not key.startswith('person:') else target}/file/{row['id']}"} if row["name"] else None}
        for row in reversed(rows[:50])]}


@router.post("/thread/{target}", status_code=201)
def send(target: str, payload: MessageCreate, user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    touch(user.id)
    key, peer, _ = participants(target, user, db)
    db.execute(messages.insert().values(thread=key, sender_id=user.id, recipient_id=peer, body=payload.body, created_at=utc_now(), read_at=utc_now() if peer == user.id else None))
    db.commit()
    return {"ok": True}


@router.post("/thread/{target}/file", status_code=201)
async def send_file(target: str, request: Request, user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    touch(user.id)
    # Bound the JSON upload before parsing; PostgreSQL stores the binary, not base64.
    limit = 4 * ((MAX_CHAT_FILE + 2) // 3) + 32768
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > limit:
            raise HTTPException(413, "Файл должен быть не больше 5 МБ")
        raw.extend(chunk)
    try:
        payload = FileMessage.model_validate_json(raw)
        content = base64.b64decode(payload.content, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, "Не удалось прочитать вложение") from None
    if not content or len(content) > MAX_CHAT_FILE:
        raise HTTPException(413, "Файл должен быть не больше 5 МБ")
    name = payload.name.replace("\\", "/").split("/")[-1]
    name = "".join(char for char in name if char.isprintable()).strip() or "file"
    key, peer, _ = participants(target, user, db)
    message_id = db.scalar(messages.insert().values(thread=key, sender_id=user.id, recipient_id=peer,
                           body=payload.body, created_at=utc_now(), read_at=utc_now() if peer == user.id else None).returning(messages.c.id))
    db.execute(attachments.insert().values(message_id=message_id, name=name, size=len(content), content=content))
    db.commit()
    return {"ok": True}


@router.get("/thread/{target}/file/{message_id}")
def download_file(target: str, message_id: int, inline: bool = False,
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    touch(user.id)
    key, _, _ = participants(target, user, db)
    row = db.execute(select(attachments.c.name, attachments.c.content).select_from(messages.join(attachments))
                     .where(messages.c.id == message_id, messages.c.thread == key, visible(user.id))).first()
    if not row:
        raise HTTPException(404, "Файл не найден")
    preview = file_preview(row.name)
    media_type = ({"pdf": "application/pdf", "image": "image/" + row.name.rsplit(".", 1)[-1].lower().replace("jpg", "jpeg")}
                  .get(preview, "application/octet-stream"))
    disposition = "inline" if inline and preview else "attachment"
    return Response(row.content, media_type=media_type,
                    headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''" + quote(row.name, safe=""),
                             "X-Content-Type-Options": "nosniff"})


@router.post("/thread/{target}/read/{through}")
def mark_read(target: str, through: int, user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    touch(user.id)
    key, _, _ = participants(target, user, db)
    db.execute(update(messages).where(messages.c.thread == key, messages.c.recipient_id == user.id,
               messages.c.id <= through, messages.c.read_at.is_(None)).values(read_at=utc_now()))
    db.commit()
    return {"ok": True}


@router.post("/presence")
def heartbeat(user: User = Depends(csrf_protected)):
    touch(user.id)
    return {"ok": True}


@router.post("/thread/{target}/typing")
def set_typing(target: str, payload: TypingState, user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    key, _, _ = participants(target, user, db)
    touch(user.id)
    with _state_lock:
        if payload.active:
            _typing[(key, user.id)] = utc_now() + TYPING_TTL
        else:
            _typing.pop((key, user.id), None)
    return {"ok": True}
