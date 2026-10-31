from datetime import date, datetime, time
from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, Time, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base
from .booking_constraints import booking_overlap_constraint
from .timeutils import utc_now


class Building(Base):
    __tablename__ = "buildings"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    address: Mapped[str | None] = mapped_column(String(255))
    image: Mapped[str | None] = mapped_column(String(500))
    color: Mapped[str] = mapped_column(String(7), default="#C81340")
    rooms: Mapped[list["Room"]] = relationship(back_populates="building")


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (UniqueConstraint("building_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id"), index=True)
    floor: Mapped[int] = mapped_column(default=1)
    floor_display: Mapped[str | None] = mapped_column(String(50))
    capacity: Mapped[int] = mapped_column()
    max_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    area: Mapped[float | None] = mapped_column(Float)
    equipment: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    usage_options: Mapped[list[str]] = mapped_column(JSON, default=list)
    images: Mapped[list[str]] = mapped_column(JSON, default=list)
    floor_plan: Mapped[str | None] = mapped_column(String(500))
    color: Mapped[str] = mapped_column(String(7), default="#C81340")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    building: Mapped[Building] = relationship(back_populates="rooms")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="room", cascade="all, delete-orphan")


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(250))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    curators: Mapped[list["DepartmentCurator"]] = relationship(back_populates="department", cascade="all, delete-orphan")


class DepartmentCurator(Base):
    __tablename__ = "department_curators"
    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    contact: Mapped[str | None] = mapped_column(String(200))
    department: Mapped[Department] = relationship(back_populates="curators")


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        Index("ix_booking_room_window", "room_id", "date", "time_start", "time_end"),
        booking_overlap_constraint(),
        CheckConstraint("time_end > time_start", name="ck_booking_time_order"),
        CheckConstraint("status IN ('pending','approved','rejected','cancelled','cancelled_by_user','cancelled_by_admin','completed','no_show','transferred')", name="ck_booking_status"),
        CheckConstraint("record_kind IN ('booking','maintenance','setup','teardown','unavailable')", name="ck_booking_record_kind"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    time_start: Mapped[time] = mapped_column(Time)
    time_end: Mapped[time] = mapped_column(Time)
    title: Mapped[str] = mapped_column(String(200))
    booking_type: Mapped[str] = mapped_column(String(50), default="other")
    group_name: Mapped[str | None] = mapped_column(String(100))
    teacher: Mapped[str | None] = mapped_column(String(200))
    booked_by: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    comment: Mapped[str | None] = mapped_column(Text)
    requested_equipment: Mapped[list[str]] = mapped_column(JSON, default=list)
    # None means the requester did not answer (records created before the question existed).
    catering_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    technical_support_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="self_service", index=True)
    customer_name: Mapped[str | None] = mapped_column(String(200))
    customer_contact: Mapped[str | None] = mapped_column(String(200))
    participants: Mapped[int | None] = mapped_column(Integer)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), index=True)
    external_channel: Mapped[str | None] = mapped_column(String(40), index=True)
    external_reference: Mapped[str | None] = mapped_column(String(120), index=True)
    external_url: Mapped[str | None] = mapped_column(String(1000))
    series_id: Mapped[str | None] = mapped_column(String(36), index=True)
    previous_booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"), index=True)
    transfer_reason: Mapped[str | None] = mapped_column(String(500))
    # Extra room of a set: points at the main booking and says what the room is for.
    parent_booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"), index=True)
    room_purpose: Mapped[str | None] = mapped_column(String(200))
    record_kind: Mapped[str] = mapped_column(String(30), default="booking", index=True)
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))
    cancellation_comment: Mapped[str | None] = mapped_column(Text)
    replacement_offered: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_customer: Mapped[bool] = mapped_column(Boolean, default=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    decision_reason: Mapped[str | None] = mapped_column(String(500))
    room: Mapped[Room] = relationship(back_populates="bookings")
    owner: Mapped["User"] = relationship(back_populates="bookings", foreign_keys=[owner_id])
    cancelled_by: Mapped["User | None"] = relationship(foreign_keys=[cancelled_by_id])
    archived_by: Mapped["User | None"] = relationship(foreign_keys=[archived_by_id])
    decided_by: Mapped["User | None"] = relationship(foreign_keys=[decided_by_id])
    department: Mapped["Department | None"] = relationship()
    previous_booking: Mapped["Booking | None"] = relationship(remote_side="Booking.id", foreign_keys=[previous_booking_id])
    events: Mapped[list["BookingEvent"]] = relationship(back_populates="booking", cascade="all, delete-orphan", order_by="BookingEvent.created_at")
    comments: Mapped[list["BookingComment"]] = relationship(back_populates="booking", cascade="all, delete-orphan", order_by="BookingComment.created_at")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("uq_users_single_admin", "role", unique=True,
                           postgresql_where=(text("role = 'admin'")),
                           sqlite_where=(text("role = 'admin'"))),)
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    position: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    department: Mapped[str | None] = mapped_column(String(200))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="user", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Bumped on every password change: sessions issued earlier stop working.
    extra_rooms_guide_seen: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    session_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_failed_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bookings: Mapped[list[Booking]] = relationship(back_populates="owner", foreign_keys=[Booking.owner_id])


class BookingHistory(Base):
    __tablename__ = "booking_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(30))
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BookingEvent(Base):
    """Append-only audit trail. Application code only inserts events."""
    __tablename__ = "booking_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    summary: Mapped[str] = mapped_column(String(500))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    booking: Mapped[Booking] = relationship(back_populates="events")
    actor: Mapped["User"] = relationship(foreign_keys=[actor_id])


class BookingAttachment(Base):
    """A file attached to one booking, or to a whole series (booking_id is then empty)."""
    __tablename__ = "booking_attachments"
    __table_args__ = (CheckConstraint("booking_id IS NOT NULL OR series_id IS NOT NULL", name="ck_attachment_target"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), index=True)
    series_id: Mapped[str | None] = mapped_column(String(36), index=True)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(100))
    content_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    uploaded_by: Mapped["User"] = relationship(foreign_keys=[uploaded_by_id])


class BookingComment(Base):
    __tablename__ = "booking_comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    booking: Mapped[Booking] = relationship(back_populates="comments")
    author: Mapped["User"] = relationship(foreign_keys=[author_id])
    resolved_by: Mapped["User | None"] = relationship(foreign_keys=[resolved_by_id])


class EmailCode(Base):
    """A one-time confirmation code sent by email (registration or password reset)."""
    __tablename__ = "email_codes"
    __table_args__ = (Index("ix_email_codes_lookup", "email", "purpose", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255))
    purpose: Mapped[str] = mapped_column(String(20))
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    requested_ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BookingDeletion(Base):
    """What a permanently deleted booking was, who removed it and when.

    Deleting a record cascades to its events and comments; this row is kept so
    the history of an erroneous record can still be checked after the deletion.
    No foreign key to bookings: the booking itself no longer exists.
    """
    __tablename__ = "booking_deletions"
    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(Integer, index=True)
    deleted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
