from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, ForeignKey, Integer, JSON, Table, select, update
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import Booking, User
from .security import admin_read_user, admin_user

router = APIRouter(prefix="/api/admin/moderation-workspace")
preferences = Table(
    "moderation_workspaces", Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("version", Integer, nullable=False),
    Column("data", JSON, nullable=False),
)
Identifier = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9:_-]+$")]
Tag = Annotated[str, Field(min_length=1, max_length=48, pattern=r"\S")]


class Folder(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: Identifier
    name: str = Field(min_length=1, max_length=70)
    parent_id: Identifier | None = None
    pinned: bool = False
    collapsed: bool = False


class Entry(BaseModel):
    folder: Identifier | None = None
    tags: list[Tag] = Field(default_factory=list, max_length=40)
    working: bool = False
    favorite: bool = False


class Workspace(BaseModel):
    version: int = Field(ge=0, le=2147483646)
    folders: list[Folder] = Field(default_factory=list, max_length=80)
    tag_catalog: list[Tag] = Field(default_factory=list, max_length=300)
    tag_colors: dict[Tag, str] = Field(default_factory=dict, max_length=300)
    entries: dict[Identifier, Entry] = Field(default_factory=dict, max_length=5000)


def _scoped_data(data: dict, scope: str) -> dict:
    workspaces = data.get("workspaces")
    if isinstance(workspaces, dict):
        return workspaces.get(scope) or {"folders": [], "entries": {}, "tag_catalog": [], "tag_colors": {}}
    if scope == "bookings":
        return data
    return {"folders": [], "entries": {}, "tag_catalog": [], "tag_colors": {}}


@router.get("")
def get_workspace(user: User = Depends(admin_read_user), db: Session = Depends(get_db),
                  scope: Literal["bookings", "moderation"] = "bookings"):
    row = db.execute(select(preferences).where(preferences.c.user_id == user.id)).mappings().first()
    return ({"version": row["version"], **_scoped_data(row["data"], scope)} if row
            else {"version": 0, "folders": [], "entries": {}, "tag_catalog": [], "tag_colors": {}})


@router.put("")
def save_workspace(payload: Workspace, user: User = Depends(admin_user), db: Session = Depends(get_db),
                   scope: Literal["bookings", "moderation"] = "bookings"):
    ids = {folder.id for folder in payload.folders}
    if (len(ids) != len(payload.folders)
            or any(folder.parent_id and folder.parent_id not in ids for folder in payload.folders)
            or any(folder.parent_id == folder.id for folder in payload.folders)
            or any(item.folder and item.folder not in ids for item in payload.entries.values())):
        raise HTTPException(422, "Проверьте папки и назначение заявок")
    parents = {folder.id: folder.parent_id for folder in payload.folders}
    for folder_id in ids:
        visited: set[str] = set()
        current: str | None = folder_id
        while current:
            if current in visited:
                raise HTTPException(422, "Папка не может находиться внутри самой себя")
            visited.add(current)
            current = parents.get(current)
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    current_row = db.execute(select(preferences).where(preferences.c.user_id == user.id)).mappings().first()
    current = current_row["version"] if current_row else None
    if (current or 0) != payload.version:
        raise HTTPException(409, "Настройки изменились в другой вкладке. Обновите страницу.")
    workspace_data = payload.model_dump(exclude={"version"})
    current_data = current_row["data"] if current_row else {}
    if isinstance(current_data.get("workspaces"), dict):
        workspaces = dict(current_data["workspaces"])
    else:
        workspaces = {"bookings": current_data} if current_data else {}
    workspaces[scope] = workspace_data
    data = {"workspaces": workspaces}
    version = payload.version + 1
    if current is None:
        db.execute(preferences.insert().values(user_id=user.id, version=version, data=data))
    else:
        db.execute(update(preferences).where(preferences.c.user_id == user.id).values(version=version, data=data))
    db.commit()
    return {"version": version, **workspace_data}


@router.get("/history")
def history(_: User = Depends(admin_read_user), db: Session = Depends(get_db)):
    fields = (Booking.id, Booking.title, Booking.date, Booking.created_at, Booking.status,
              Booking.series_id, Booking.parent_booking_id, Booking.external_reference,
              Booking.customer_name, Booking.booked_by, Booking.owner_id)
    rows = db.execute(select(*fields).where(Booking.record_kind == "booking", Booking.status != "pending"))
    return [dict(row) for row in rows.mappings()]
