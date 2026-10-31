"""Regression tests for the full audit of 2026-10-27 (items К1–К5, С1–С12, М1–М18).

Same setup as test_request_flow: services against in-memory SQLite with a fixed
clock and a no-op advisory lock.
"""
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from openpyxl import Workbook
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import excel_import, main
from app.models import Base, Booking, BookingAttachment, Building, Room, User
from app.schemas import (AvailabilityRequest, BatchBookingCreate, BookingCreate, BookingTransferRequest,
                         BookingUpdate, RoomCreate)
from app.services import availability
from app.services import booking_lifecycle as lifecycle
from app.services import bookings as bookings_service
from app.services import operations
from app.timeutils import utc_now

NOW = datetime(2029, 12, 20, 9, 0)
DAY = date(2030, 1, 14)


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    event.listen(engine, "connect", lambda conn, _: conn.create_function("pg_advisory_xact_lock", 1, lambda key: None))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    db = factory()
    clock = SimpleNamespace(now=NOW)
    for module in (lifecycle, bookings_service, main):
        monkeypatch.setattr(module, "local_now", lambda: clock.now)
    monkeypatch.setattr(main, "local_today", lambda: clock.now.date())
    building = Building(name="Корпус 1")
    db.add(building); db.flush()
    rooms = [Room(number="101", name="Ауд 1", building_id=building.id, capacity=30, max_capacity=50),
             Room(number="102", name="Ауд 2", building_id=building.id, capacity=30)]
    users = {name: User(email=f"{name}@test.ru", full_name=name.title(), password_hash="x",
                        role="admin" if name == "admin" else "user") for name in ("admin", "anna")}
    db.add_all(rooms + list(users.values())); db.commit()
    yield SimpleNamespace(db=db, factory=factory, rooms=rooms, **users)
    db.close()


def book(env, user, *, day=DAY, start="10:00", end="12:00", room=0, participants=10, **extra):
    payload = BookingCreate(catering_required=extra.pop("catering_required", False), technical_support_required=extra.pop("technical_support_required", False), room_id=env.rooms[room].id, date=day, time_start=start, time_end=end, title="Семинар",
                            participants=participants, **extra)
    return bookings_service.create_booking(env.db, payload, user)


def expect(code, call, *args, **kwargs):
    with pytest.raises(HTTPException) as exc:
        call(*args, **kwargs)
    assert exc.value.status_code == code
    return exc.value.detail


# --- К2: Excel import -----------------------------------------------------------

@pytest.mark.parametrize("comment,window", [
    ("с 10:00 до 12:30", (time(10), time(12, 30))),
    ("9.30-11.00", (time(9, 30), time(11))),
    ("30.10-31.10", (time(8), time(22))),          # dates, used to crash with "hour must be in 0..23"
    ("12.10 до 15.10", (time(8), time(22))),       # dates, used to become 12:10–15:10
    (None, (time(8), time(22))),
])
def test_excel_comment_times(comment, window):
    assert excel_import._time_window(comment) == window


def _workbook(path, cells):
    sheet = Workbook().active
    sheet.title = "2030"
    sheet.cell(1, 1, "Дата/аудитория"); sheet.cell(1, 2, "Корпус 1"); sheet.cell(3, 2, "101")
    for row, (day, value) in enumerate(cells, start=4):
        sheet.cell(row, 1, datetime.combine(day, time())); sheet.cell(row, 2, value)
    sheet.parent.save(path)


def test_excel_import_skips_overlaps_instead_of_failing(env, tmp_path, monkeypatch):
    monkeypatch.setattr(excel_import, "SessionLocal", env.factory)
    book(env, env.admin)                      # approved 10:00–12:00 on DAY in room 101
    path = tmp_path / "history.xlsx"
    _workbook(path, [(DAY, "Кафедра истории"), (DAY + timedelta(days=1), "Кафедра истории"),
                     (DAY + timedelta(days=1), "Кафедра истории")])
    result = excel_import.import_excel(str(path), "admin@test.ru", confirm=True)
    assert result["imported"] == 1
    assert result["skipped_overlap"] == 2  # one against the database, one against the same import
    assert len(result["overlaps"]) == 2
    # A second run neither duplicates records nor the department.
    again = excel_import.import_excel(str(path), "admin@test.ru", confirm=True)
    assert again.get("imported", 0) == 0


# --- К3: room deactivation ---------------------------------------------------------

def test_room_with_future_bookings_cannot_be_switched_off(env):
    book(env, env.anna)
    detail = expect(409, main.deactivate_room, env.rooms[0].id, env.admin, env.db)
    assert "14.01.2030" in detail
    assert main.deactivate_room(env.rooms[1].id, env.admin, env.db) == {"ok": True}


def test_booking_in_switched_off_room_stays_editable_but_cannot_move_in(env):
    item = book(env, env.admin)
    env.rooms[0].is_active = False; env.db.commit()
    main.update_admin_booking(item.id, BookingUpdate(title="Новое название"), env.admin, env.db)
    assert env.db.get(Booking, item.id).title == "Новое название"
    other = book(env, env.admin, room=1)
    expect(409, main.update_admin_booking, other.id, BookingUpdate(room_id=env.rooms[0].id), env.admin, env.db)


# --- К4 / С4 / С7: transfers ------------------------------------------------------

def _transfer(env, item, **extra):
    payload = BookingTransferRequest(catering_required=extra.pop("catering_required", False), technical_support_required=extra.pop("technical_support_required", False), room_id=env.rooms[1].id, date=DAY, time_start="14:00", time_end="16:00",
                                     title=item.title, reason="Попросил заказчик", **extra)
    return operations.transfer_booking(env.db, item, payload, env.admin)


def test_transfer_keeps_single_booking_single_and_keeps_its_details(env):
    item = book(env, env.admin, group_name="ИБ-21", teacher="Петров")
    moved = _transfer(env, item)
    assert moved.series_id is None and moved.previous_booking_id == item.id
    assert (moved.group_name, moved.teacher) == ("ИБ-21", "Петров")


def test_replacement_of_a_transfer_cannot_be_deleted(env):
    moved = _transfer(env, book(env, env.admin))
    expect(409, lifecycle.delete_booking_record, env.db, moved)
    expect(409, lifecycle.delete_booking_records, env.db, [moved.id])


# --- К5: aware UTC ---------------------------------------------------------------

def test_timestamps_are_aware_utc():
    assert utc_now().tzinfo is timezone.utc


# --- С1: maximum capacity ----------------------------------------------------------

def test_maximum_capacity_is_the_hard_limit(env):
    assert book(env, env.anna, participants=40).status == "pending"
    expect(400, book, env, env.anna, participants=51, start="14:00", end="16:00")
    found = availability.build_availability(env.db, AvailabilityRequest(date=DAY, time_start="14:00", time_end="16:00",
                                                                         participants=40))
    assert [(room["number"], room["over_capacity"]) for room in found["free"]] == [("101", True)]


def test_room_maximum_cannot_be_below_capacity():
    with pytest.raises(ValidationError):
        RoomCreate(number="1", name="Ауд", building_id=1, floor=1, capacity=30, max_capacity=20)


# --- С2: validation instead of 500 ----------------------------------------------------

def test_long_fields_and_cleared_required_fields_are_rejected():
    with pytest.raises(ValidationError):
        BookingCreate(catering_required=False, technical_support_required=False, room_id=1, date=DAY, time_start="10:00", time_end="11:00", title="Семинар", group_name="x" * 101)
    for field in ("title", "date", "room_id"):
        with pytest.raises(ValidationError):
            BookingUpdate(**{field: None})
    assert BookingUpdate(comment=None).model_fields_set == {"comment"}


def test_unknown_department_is_404(env):
    item = book(env, env.admin)
    expect(404, main.update_admin_booking, item.id, BookingUpdate(department_id=999), env.admin, env.db)


# --- С3: "do not notify" ---------------------------------------------------------

def test_cancellation_without_notification_is_not_shown_to_the_owner(env):
    quiet, loud = book(env, env.anna), book(env, env.anna, start="14:00", end="16:00")
    lifecycle.cancel_booking_record(env.db, quiet, env.admin, reason="Ремонт", comment="Тихо",
                                    replacement_offered=False, notify_customer=False)
    lifecycle.cancel_booking_record(env.db, loud, env.admin, reason="Ремонт", comment="Громко",
                                    replacement_offered=False, notify_customer=True)
    notes = main.my_notifications(0, env.anna, env.db)
    assert [note["booking_id"] for note in notes if note["type"] == "cancelled_by_admin"] == [loud.id]


# --- С9: alternatives ------------------------------------------------------------

def test_alternatives_include_rooms_of_another_building(env):
    found = availability.build_availability(env.db, AvailabilityRequest(date=DAY, time_start="10:00", time_end="12:00",
                                                                         building_id=999))
    assert not found["free"]
    assert {room["number"] for room in found["alternatives"]} == {"101", "102"}
    assert "другой корпус" in found["alternatives"][0]["alternative_reason"]


def test_nearest_booking_is_the_one_closest_to_the_requested_time(env):
    book(env, env.admin, start="08:00", end="09:00")
    book(env, env.admin, start="15:00", end="16:00")
    found = availability.build_availability(env.db, AvailabilityRequest(date=DAY, time_start="12:00", time_end="14:00"))
    room = next(room for room in found["free"] if room["number"] == "101")
    assert room["nearest_booking"]["time_start"] == "15:00"


# --- М3 / М4: bulk archive and delete --------------------------------------------------

def test_series_is_deleted_in_one_transaction_with_its_files(env):
    payload = BatchBookingCreate(catering_required=False, technical_support_required=False, room_ids=[env.rooms[0].id], date=DAY, date_end=DAY + timedelta(days=2),
                                 time_start="10:00", time_end="12:00", title="Курс")
    items = operations.create_series(env.db, payload, env.admin)
    env.db.add(BookingAttachment(series_id=items[0].series_id, uploaded_by_id=env.admin.id, original_name="план.pdf",
                                 stored_name="plan.pdf", content_type="application/pdf", size=1))
    env.db.commit()
    stored = lifecycle.delete_booking_records(env.db, [item.id for item in items])
    assert stored == ["plan.pdf"]
    assert env.db.scalar(select(Booking.id)) is None
    assert env.db.scalar(select(BookingAttachment.id)) is None


def test_archiving_several_records_is_all_or_nothing(env):
    past = book(env, env.admin)
    future = book(env, env.admin, day=DAY + timedelta(days=1))
    env.db.commit()
    main_clock = lifecycle.local_now
    lifecycle.local_now = lambda: datetime(2030, 1, 14, 13, 0)
    try:
        expect(409, lifecycle.set_bookings_archived, env.db, [past.id, future.id], env.admin, True)
        env.db.rollback()
        assert env.db.get(Booking, past.id).archived_at is None
        assert lifecycle.set_bookings_archived(env.db, [past.id], env.admin, True) == 1
    finally:
        lifecycle.local_now = main_clock


# --- М11: booking horizon ------------------------------------------------------------

def test_booking_too_far_ahead_is_rejected(env):
    expect(400, book, env, env.anna, day=NOW.date() + timedelta(days=800))
