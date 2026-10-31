"""Files attached to bookings.

A file belongs either to one booking or to a whole series (then every date of
the series shows it). Files are kept outside the public /api/uploads folder and
are served only to an administrator or to the owner of the booking.
"""
import os
from pathlib import Path
import unicodedata
from urllib.parse import unquote
import uuid

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from ..models import Booking, BookingAttachment, User
from .booking_lifecycle import CLOSED_BOOKING_STATUSES
from .bookings import record_event

ATTACHMENTS_DIR = Path(os.getenv("ATTACHMENTS_DIR") or Path(__file__).resolve().parents[2] / "storage" / "attachments")
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_FILES_PER_TARGET = 10
# Extension -> media type. Only these types can be attached.
ALLOWED_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
    "txt": "text/plain; charset=utf-8", "csv": "text/csv; charset=utf-8", "rtf": "application/rtf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation",
    "zip": "application/zip",
}
# Types a browser can show by itself; everything else is downloaded.
INLINE_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "gif", "webp", "txt"}
ALLOWED_LABEL = "PDF, Word, Excel, PowerPoint, OpenDocument, TXT, CSV, RTF, ZIP и изображения"


def _extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def clean_file_name(raw: str | None) -> str:
    name = unquote(raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in unicodedata.normalize("NFC", name) if unicodedata.category(ch)[0] != "C").strip(" .")
    if not name:
        raise HTTPException(400, "Не передано имя файла")
    if len(name) > 200:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 200 - len(ext) - 1] + dot + ext) if dot else name[:200]
    return name


def attachment_to_dict(item: BookingAttachment) -> dict:
    return {
        "id": item.id, "name": item.original_name, "size": item.size,
        "content_type": item.content_type.split(";")[0],
        "scope": "booking" if item.booking_id else "series",
        "booking_id": item.booking_id, "series_id": item.series_id,
        "uploaded_by": item.uploaded_by.full_name if item.uploaded_by else None,
        "uploaded_by_id": item.uploaded_by_id,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "viewable": _extension(item.original_name) in INLINE_EXTENSIONS,
        "url": f"/api/attachments/{item.id}",
        "download_url": f"/api/attachments/{item.id}?download=1",
    }


def attachments_for(db: Session, bookings) -> dict[int, list[dict]]:
    """Files of each booking (its own files and its series' files) by booking id, in one query."""
    bookings = list(bookings)
    ids = [item.id for item in bookings]
    series_ids = list({item.series_id for item in bookings if item.series_id})
    if not ids:
        return {}
    condition = BookingAttachment.booking_id.in_(ids)
    if series_ids:
        condition = or_(condition, BookingAttachment.series_id.in_(series_ids) & BookingAttachment.booking_id.is_(None))
    rows = db.scalars(select(BookingAttachment).options(joinedload(BookingAttachment.uploaded_by))
                      .where(condition).order_by(BookingAttachment.created_at, BookingAttachment.id)).all()
    by_booking: dict[int, list] = {}
    by_series: dict[str, list] = {}
    for row in rows:
        target = by_booking.setdefault(row.booking_id, []) if row.booking_id else by_series.setdefault(row.series_id, [])
        target.append(attachment_to_dict(row))
    return {item.id: by_series.get(item.series_id, []) + by_booking.get(item.id, []) for item in bookings}


def add_attachments(db: Session, bookings: list, rows: list[dict]) -> list[dict]:
    """Put the "attachments" list into serialized bookings (rows follow the order of bookings)."""
    files = attachments_for(db, bookings)
    for item, row in zip(bookings, rows):
        row["attachments"] = files.get(item.id, [])
    return rows


# Leading bytes of each binary format. A renamed file (an .exe called report.pdf) is
# refused. Plain text (txt, csv) has no signature and only has to look like text.
_ZIP = (b"PK\x03\x04", b"PK\x05\x06")
_OLE = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",)
SIGNATURES = {
    "pdf": (b"%PDF-",), "png": (b"\x89PNG\r\n\x1a\n",), "jpg": (b"\xff\xd8\xff",), "jpeg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"), "webp": (b"RIFF",), "rtf": (b"{\\rtf",),
    "doc": _OLE, "xls": _OLE, "ppt": _OLE,
    "docx": _ZIP, "xlsx": _ZIP, "pptx": _ZIP, "odt": _ZIP, "ods": _ZIP, "odp": _ZIP, "zip": _ZIP,
}


def _content_matches(extension: str, content: bytes) -> bool:
    if extension in ("txt", "csv"):
        # Plain text: refuse executables and other binaries that only carry a text name.
        return b"\x00" not in content[:4096] and not content.startswith((b"MZ", b"\x7fELF"))
    if not any(content.startswith(magic) for magic in SIGNATURES.get(extension, (b"",))):
        return False
    return extension != "webp" or content[8:12] == b"WEBP"


def _can_access(user: User, bookings: list[Booking]) -> bool:
    return user.role == "admin" or any(item.owner_id == user.id for item in bookings)


def _target_bookings(db: Session, *, booking_id: int | None = None, series_id: str | None = None) -> list[Booking]:
    if booking_id is not None:
        item = db.get(Booking, booking_id)
        return [item] if item else []
    return list(db.scalars(select(Booking).where(Booking.series_id == series_id)))


def save_attachment(db: Session, user: User, content: bytes, raw_name: str | None, *,
                    booking_id: int | None = None, series_id: str | None = None) -> dict:
    bookings = _target_bookings(db, booking_id=booking_id, series_id=series_id)
    if not bookings or not _can_access(user, bookings):
        raise HTTPException(404, "Бронирование не найдено")
    if user.role != "admin" and all(item.status in CLOSED_BOOKING_STATUSES for item in bookings):
        raise HTTPException(409, "К закрытой заявке нельзя добавить файлы")
    name = clean_file_name(raw_name)
    extension = _extension(name)
    if extension not in ALLOWED_TYPES:
        raise HTTPException(415, f"Этот тип файла нельзя прикрепить. Разрешены: {ALLOWED_LABEL}")
    if not content:
        raise HTTPException(400, "Файл пустой")
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(413, "Размер файла должен быть не более 20 МБ")
    if not _content_matches(extension, content):
        raise HTTPException(415, f"Содержимое файла не похоже на .{extension}. Проверьте файл или сохраните его заново")
    # Parallel uploads to one booking or series wait for each other here, so the
    # file limit below cannot be passed by sending several files at once.
    lock_rows = select(Booking.id).where(Booking.id.in_([item.id for item in bookings])).order_by(Booking.id)
    if db.get_bind().dialect.name == "postgresql":
        db.execute(lock_rows.with_for_update())
    target = BookingAttachment.booking_id == booking_id if booking_id is not None else (
        (BookingAttachment.series_id == series_id) & BookingAttachment.booking_id.is_(None))
    if len(db.scalars(select(BookingAttachment.id).where(target)).all()) >= MAX_FILES_PER_TARGET:
        raise HTTPException(409, f"К одной заявке можно прикрепить не более {MAX_FILES_PER_TARGET} файлов")
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.{extension}"
    (ATTACHMENTS_DIR / stored_name).write_bytes(content)
    item = BookingAttachment(booking_id=booking_id, series_id=None if booking_id is not None else series_id,
                             uploaded_by_id=user.id, original_name=name, stored_name=stored_name,
                             content_type=ALLOWED_TYPES[extension], size=len(content))
    try:
        db.add(item); db.flush()
        for booking in bookings:
            record_event(db, booking, user, "attachment_added", f"Прикреплён файл «{name}»", {"attachment_id": item.id})
        db.commit()
    except Exception:
        db.rollback()
        (ATTACHMENTS_DIR / stored_name).unlink(missing_ok=True)
        raise
    db.refresh(item)
    return attachment_to_dict(item)


def get_attachment_for(db: Session, user: User, attachment_id: int) -> tuple[BookingAttachment, Path]:
    item = db.get(BookingAttachment, attachment_id)
    if not item:
        raise HTTPException(404, "Файл не найден")
    bookings = _target_bookings(db, booking_id=item.booking_id, series_id=item.series_id)
    if not (_can_access(user, bookings) or item.uploaded_by_id == user.id):
        raise HTTPException(404, "Файл не найден")
    path = ATTACHMENTS_DIR / item.stored_name
    if not path.is_file():
        raise HTTPException(404, "Файл не найден на сервере")
    return item, path


def inline_allowed(item: BookingAttachment) -> bool:
    return _extension(item.original_name) in INLINE_EXTENSIONS


def delete_attachment(db: Session, user: User, attachment_id: int) -> None:
    item, _ = get_attachment_for(db, user, attachment_id)
    if user.role != "admin" and item.uploaded_by_id != user.id:
        raise HTTPException(403, "Удалить файл может только тот, кто его прикрепил, или администратор")
    bookings = _target_bookings(db, booking_id=item.booking_id, series_id=item.series_id)
    for booking in bookings:
        record_event(db, booking, user, "attachment_removed", f"Удалён файл «{item.original_name}»", {"attachment_id": item.id})
    stored_name = item.stored_name
    db.delete(item)
    db.commit()
    remove_unused_files(db, [stored_name])


def copy_booking_attachments(db: Session, source: Booking, target: Booking) -> None:
    """A transferred booking keeps the files of the original one (both rows point at the same file)."""
    for row in db.scalars(select(BookingAttachment).where(BookingAttachment.booking_id == source.id)):
        db.add(BookingAttachment(booking_id=target.id, uploaded_by_id=row.uploaded_by_id, original_name=row.original_name,
                                 stored_name=row.stored_name, content_type=row.content_type, size=row.size,
                                 created_at=row.created_at))


def stored_names_of(db: Session, booking_id: int) -> list[str]:
    return list(db.scalars(select(BookingAttachment.stored_name).where(BookingAttachment.booking_id == booking_id)))


def remove_unused_files(db: Session, stored_names: list[str]) -> None:
    for name in set(stored_names):
        if not db.scalar(select(BookingAttachment.id).where(BookingAttachment.stored_name == name).limit(1)):
            (ATTACHMENTS_DIR / name).unlink(missing_ok=True)
