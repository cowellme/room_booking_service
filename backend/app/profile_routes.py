from pathlib import Path
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_routes import user_json
from .database import get_db
from .http_body import read_limited
from .models import Booking, User
from .schemas import ProfileUpdate
from .security import csrf_protected, current_user
from .timeutils import local_today

router = APIRouter(prefix="/api/profile", tags=["profile"])
UPLOAD_DIR = Path(__file__).resolve().parents[1] / "uploads" / "avatars"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
AVATAR_MAX_BYTES = 5 * 1024 * 1024
IMAGE_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}


@router.get("/extra-rooms-guide")
def extra_rooms_guide_status(user: User = Depends(current_user)):
    return {"seen": user.extra_rooms_guide_seen}


@router.post("/extra-rooms-guide/seen")
def mark_extra_rooms_guide_seen(user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    user.extra_rooms_guide_seen = True
    db.commit()
    return {"seen": True}


@router.put("")
def update_profile(payload: ProfileUpdate, user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    old_name = user.full_name
    user.full_name = payload.full_name.strip()
    user.position = payload.position or None
    user.phone = payload.phone or None
    user.department = payload.department or None
    for booking in db.scalars(select(Booking).where(
        Booking.owner_id == user.id,
        Booking.date >= local_today(),
        Booking.status.in_(("pending", "approved")),
    )):
        booking.booked_by = user.full_name
        if booking.customer_name == old_name:
            booking.customer_name = user.full_name
    db.commit()
    db.refresh(user)
    return {"user": user_json(user)}


@router.post("/avatar")
async def upload_avatar(request: Request, user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    content_type = request.headers.get("content-type", "").split(";")[0]
    extensions = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
    if content_type not in extensions:
        raise HTTPException(415, "Разрешены JPG, PNG и WEBP")
    content = await read_limited(request, AVATAR_MAX_BYTES, "Размер изображения должен быть не более 5 МБ")
    if not content:
        raise HTTPException(413, "Размер изображения должен быть не более 5 МБ")
    if not any(content.startswith(magic) for magic in IMAGE_SIGNATURES[content_type]) or (
            content_type == "image/webp" and content[8:12] != b"WEBP"):
        raise HTTPException(415, "Файл не похож на изображение JPG, PNG или WEBP")
    if user.avatar_url:
        (UPLOAD_DIR / Path(user.avatar_url).name).unlink(missing_ok=True)
    filename = f"{user.id}-{uuid.uuid4().hex}.{extensions[content_type]}"
    (UPLOAD_DIR / filename).write_bytes(content)
    user.avatar_url = f"/api/uploads/avatars/{filename}"
    db.commit()
    db.refresh(user)
    return {"user": user_json(user)}


@router.delete("/avatar")
def delete_avatar(user: User = Depends(csrf_protected), db: Session = Depends(get_db)):
    if user.avatar_url:
        (UPLOAD_DIR / Path(user.avatar_url).name).unlink(missing_ok=True)
    user.avatar_url = None
    db.commit()
    db.refresh(user)
    return {"user": user_json(user)}
