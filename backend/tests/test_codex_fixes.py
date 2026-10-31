"""Regression tests for the Codex audit of 2026-10-27 (items still open after the full audit).

Same setup as test_audit_fixes: services against in-memory SQLite with a fixed clock.
"""
from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app import catalog, excel_import, main
from app.models import Booking, BookingDeletion, BookingEvent, Department, Room
from app.schemas import (BatchBookingCreate, BookingCreate, BookingUpdate, PhoneBookingCreate, RoomCreate,
                         ServiceBlockCreate)
from app.services import analytics, operations
from app.services import bookings as bookings_service

from tests.test_audit_fixes import DAY, _workbook, book, env, expect  # noqa: F401 (fixture)


def user_payload(env, **overrides):
    data = dict(catering_required=False, technical_support_required=False, room_id=env.rooms[0].id, date=DAY, time_start="10:00", time_end="12:00", title="Семинар",
                participants=10, customer_name="Анна Иванова", customer_contact="+7 900 000-00-00",
                department_name="Кафедра истории", external_reference="ЗАЯВКА-42")
    data.update(overrides)
    return BookingCreate(**data)


# --- 9: required fields on the server ----------------------------------------------

@pytest.mark.parametrize("missing", ["participants", "customer_name", "department_name", "external_reference"])
def test_user_request_needs_the_same_fields_as_the_form(env, missing):
    payload = user_payload(env, **{missing: None})
    detail = expect(422, main.create_booking, payload, env.anna, env.db)
    assert "Заполните обязательные поля" in detail
    assert main.create_booking(user_payload(env), env.anna, env.db)["status"] == "pending"


@pytest.mark.parametrize("role", ["admin", "anna"])
def test_request_number_required_for_both_roles_and_phone_optional(env, role):
    actor = getattr(env, role)
    for number in (None, "", "   "):
        detail = expect(422, main.create_booking, user_payload(env, external_reference=number), actor, env.db)
        assert "номер заявки" in detail
    result = main.create_booking(user_payload(env, external_reference="  ВШГУ-123  ", customer_contact=None), actor, env.db)
    assert result["external_reference"] == "ВШГУ-123"
    assert result["status"] == ("approved" if role == "admin" else "pending")


@pytest.mark.parametrize("role", ["admin", "anna"])
def test_series_requires_number_and_saves_it_for_every_booking(env, role):
    actor = getattr(env, role)
    payload = BatchBookingCreate(catering_required=False, technical_support_required=False, room_ids=[env.rooms[0].id], date=DAY, date_end=DAY + timedelta(days=1),
                                 time_start="10:00", time_end="12:00", title="Курс", participants=10,
                                 customer_name="Анна Иванова", department_name="Кафедра истории")
    endpoint = main.create_booking_series if role == "admin" else main.create_user_booking_series
    assert "номер заявки" in expect(422, endpoint, payload, actor, env.db)
    payload.external_reference = "СЕРИЯ-42"
    result = endpoint(payload, actor, env.db)
    records = env.db.scalars(select(Booking).where(Booking.id.in_(result["booking_ids"]))).all()
    assert len(records) == 2
    assert all(item.external_reference == "СЕРИЯ-42" for item in records)


def test_phone_booking_requires_participants(env):
    with pytest.raises(ValidationError):
        PhoneBookingCreate(catering_required=False, technical_support_required=False, room_id=1, date=DAY, time_start="10:00", time_end="12:00", title="Звонок",
                           customer_name="Анна", customer_contact="+7 900", department_id=1)


# --- 11: whitespace ----------------------------------------------------------------

def test_title_of_spaces_is_rejected_and_text_is_trimmed():
    with pytest.raises(ValidationError):
        BookingCreate(catering_required=False, technical_support_required=False, room_id=1, date=DAY, time_start="10:00", time_end="12:00", title="  ")
    with pytest.raises(ValidationError):
        BatchBookingCreate(catering_required=False, technical_support_required=False, room_ids=[1], date=DAY, date_end=DAY, time_start="10:00", time_end="12:00", title=" \t ")
    assert BookingCreate(catering_required=False, technical_support_required=False, room_id=1, date=DAY, time_start="10:00", time_end="12:00", title="  Лекция ").title == "Лекция"


# --- 12: seconds -------------------------------------------------------------------

def test_seconds_cannot_cheat_the_time_step(env):
    detail = expect(400, book, env, env.admin, start="10:00:59", end="10:30:01")
    assert "без секунд" in detail


# --- 8: service blocks ---------------------------------------------------------------

def test_service_blocks_have_a_total_limit(env):
    payload = ServiceBlockCreate(room_ids=list(range(1, 11)), date=DAY, date_end=DAY + timedelta(days=300),
                                 time_start="10:00", time_end="12:00", record_kind="maintenance",
                                 title="Ремонт", reason="Плановый ремонт")
    assert "Слишком много блокировок" in expect(400, operations.create_service_blocks, env.db, payload, env.admin)


# --- 14: department created twice ---------------------------------------------------

def test_typed_department_reuses_a_row_created_meanwhile(env, monkeypatch):
    first = bookings_service.resolve_typed_department(env.db, "Отдел кадров", env.admin)
    env.db.commit()
    # Simulate the race: the lookup misses, the insert then hits the unique code.
    real_scalar = env.db.scalar
    calls = {"n": 0}

    def scalar(statement, *args, **kwargs):
        calls["n"] += 1
        return None if calls["n"] <= 2 else real_scalar(statement, *args, **kwargs)
    monkeypatch.setattr(env.db, "scalar", scalar)
    again = bookings_service.resolve_typed_department(env.db, "Отдел кадров", env.admin)
    assert again.id == first.id
    assert len(env.db.execute(select(Department.id)).all()) == 1


# --- 15: room editing ----------------------------------------------------------------

def room_form(env, **overrides):
    data = dict(number="101", name="Ауд 1", building_id=env.rooms[0].building_id, floor=1, capacity=30,
                max_capacity=50)
    data.update(overrides)
    return RoomCreate(**data)


def test_room_update_checks_building_and_duplicate_number(env):
    expect(404, main.update_room, env.rooms[0].id, room_form(env, building_id=999), env.admin, env.db)
    expect(409, main.update_room, env.rooms[0].id, room_form(env, number="102"), env.admin, env.db)
    assert main.update_room(env.rooms[0].id, room_form(env, name="Новое имя"), env.admin, env.db) == {"ok": True}


def test_capacity_cannot_drop_below_future_bookings(env):
    book(env, env.anna, participants=40)
    detail = expect(409, main.update_room, env.rooms[0].id, room_form(env, max_capacity=35), env.admin, env.db)
    assert "40 чел." in detail
    assert main.update_room(env.rooms[0].id, room_form(env, max_capacity=40), env.admin, env.db) == {"ok": True}


# --- 16: deletion log ---------------------------------------------------------------

def test_deleted_booking_leaves_a_record(env):
    item = book(env, env.admin)
    main.delete_admin_booking(item.id, env.admin, env.db)
    assert env.db.get(Booking, item.id) is None
    log = env.db.scalar(select(BookingDeletion).where(BookingDeletion.booking_id == item.id))
    assert log.deleted_by_id == env.admin.id
    assert log.snapshot["title"] == "Семинар" and log.snapshot["date"] == DAY.isoformat()
    assert [event["type"] for event in log.snapshot["events"]][:1] == ["created"]


# --- 21: edit history -----------------------------------------------------------------

def test_edit_history_keeps_previous_values_of_every_field(env):
    item = book(env, env.admin, customer_contact="+7 900 111-11-11")
    main.update_admin_booking(item.id, BookingUpdate(customer_contact="+7 900 222-22-22", participants=20),
                              env.admin, env.db)
    event = env.db.scalar(select(BookingEvent).where(BookingEvent.booking_id == item.id,
                                                     BookingEvent.event_type == "updated"))
    assert event.data["changes"]["customer_contact"] == {"before": "+7 900 111-11-11", "after": "+7 900 222-22-22"}
    assert event.data["changes"]["participants"] == {"before": 10, "after": 20}
    assert "title" not in event.data["changes"]


# --- 18: Excel source includes the file ----------------------------------------------

def test_same_cell_of_another_workbook_is_imported(env, tmp_path, monkeypatch):
    monkeypatch.setattr(excel_import, "SessionLocal", env.factory)
    first, second = tmp_path / "2029.xlsx", tmp_path / "2030.xlsx"
    _workbook(first, [(DAY, "Кафедра истории")])
    _workbook(second, [(DAY + timedelta(days=1), "Кафедра истории")])
    assert excel_import.import_excel(str(first), "admin@test.ru", confirm=True)["imported"] == 1
    assert excel_import.import_excel(str(second), "admin@test.ru", confirm=True)["imported"] == 1
    refs = env.db.scalars(select(Booking.external_reference).where(Booking.source == "excel_import")).all()
    assert sorted(refs) == ["2029.xlsx:2030!B4", "2030.xlsx:2030!B4"]
    assert excel_import.import_excel(str(first), "admin@test.ru", confirm=True).get("imported", 0) == 0


# --- 19: catalog update keeps bookings ----------------------------------------------------

def test_sync_catalog_keeps_bookings_and_room_ids(env, monkeypatch, tmp_path):
    monkeypatch.setattr(catalog, "SessionLocal", env.factory)
    item = book(env, env.anna)
    data_file = tmp_path / "catalog.json"
    data_file.write_text('''{"buildings": [{"code": "K1", "name": "Корпус 1", "address": "ул. 1", "image": "", "color": "#000000"}],
      "rooms": [{"building_code": "K1", "number": "101", "name": "Большая", "floor": 1, "floor_display": "1",
                 "capacity": 35, "area": null, "type": "lecture", "equipment": [], "usage_options": [],
                 "description": "", "images": [], "floor_plan": null, "color": "#000000"},
                {"building_code": "K1", "number": "103", "name": "Новая", "floor": 1, "floor_display": "1",
                 "capacity": 20, "area": null, "type": "seminar", "equipment": [], "usage_options": [],
                 "description": "", "images": [], "floor_plan": null, "color": "#000000"}]}''', encoding="utf-8")
    monkeypatch.setattr(catalog, "CATALOG_FILE", data_file)
    preview = catalog.sync_catalog(confirm=False)
    assert preview["rooms_added"] == 1 and preview["rooms_updated"] == 1 and preview["rooms_not_in_file"] == ["Корпус 1: 102"]
    catalog.sync_catalog(confirm=True)
    env.db.expire_all()
    room = env.db.get(Room, env.rooms[0].id)
    assert room.name == "Большая" and room.capacity == 35 and room.max_capacity == 50
    assert env.db.get(Booking, item.id).room_id == room.id
    assert catalog.count_bookings() == 1


# --- 40: analytics reads only the relevant period --------------------------------------

def test_analytics_skips_old_closed_history(env):
    old = book(env, env.admin)
    old.status = "completed"; old.date = DAY - timedelta(days=400)
    old.created_at = old.created_at - timedelta(days=400)
    env.db.commit()
    recent = book(env, env.anna, room=1)
    ids = {item.id for request in analytics._requests(env.db, DAY - timedelta(days=30)) for item in request.records}
    assert ids == {recent.id}
    assert len(analytics._requests(env.db)) == 2
