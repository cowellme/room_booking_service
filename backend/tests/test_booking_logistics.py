from datetime import timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import main
from app.models import Booking
from app.schemas import BatchBookingCreate, BookingCreate, BookingTransferRequest, BookingUpdate, PhoneBookingCreate
from test_request_flow import DAY, env


ANSWERS = {
    "event_location": "remote_site",
    "catering_required": False,
    "catering_storage_required": True,
    "operations_hq_required": False,
    "vip_room_required": True,
}


def form(env):
    return dict(room_id=env.rooms[0].id, date=DAY, time_start="10:00", time_end="12:00",
                title="Образовательная программа", participants=12, customer_name="Иванов И. И.",
                department_name="ИГСУ", external_reference="2026-42", **ANSWERS)


@pytest.mark.parametrize("field", list(ANSWERS)[1:])
def test_update_rejects_non_boolean_answers(field):
    with pytest.raises(ValidationError):
        BookingUpdate.model_validate({field: "no"})


def test_location_must_be_a_supported_option():
    with pytest.raises(ValidationError):
        BookingUpdate(event_location="other")


@pytest.mark.parametrize("field", list(ANSWERS))
def test_requests_reject_unanswered_questions(env, field):
    data = form(env)
    data.pop(field)
    if field == "catering_required":
        with pytest.raises(ValidationError):
            BookingCreate(**data)
    else:
        with pytest.raises(HTTPException) as error:
            main.create_booking(BookingCreate(**data), env.anna, env.db)
        assert error.value.status_code == 422
        assert "обязательные вопросы" in error.value.detail


@pytest.mark.parametrize("role", ["anna", "admin"])
@pytest.mark.parametrize("series", [False, True])
def test_answers_are_saved_without_pyrus_submission(env, role, series):
    actor = getattr(env, role)
    data = form(env)
    if series:
        data.update(room_ids=[env.rooms[0].id], date_end=DAY + timedelta(days=1))
        route = main.create_booking_series if role == "admin" else main.create_user_booking_series
        ids = route(BatchBookingCreate(**data), actor, env.db)["booking_ids"]
    elif role == "admin":
        ids = [main.create_phone_booking(PhoneBookingCreate(**data), actor, env.db)["id"]]
    else:
        data["extra_rooms"] = [{"room_id": env.rooms[1].id, "purpose": "Склад кейтеринга"}]
        result = main.create_booking(BookingCreate(**data), actor, env.db)
        ids = [result["id"]]
        assert {key: result[key] for key in ANSWERS} == ANSWERS
        ids.extend(item.id for item in env.db.query(Booking).filter_by(parent_booking_id=result["id"]))
        assert len(ids) == 2
    for record_id in ids:
        record = env.db.get(Booking, record_id)
        assert {key: getattr(record, key) for key in ANSWERS} == ANSWERS
        assert record.technical_support_required is None


def test_transfer_keeps_new_answers(env):
    data = form(env)
    initial = main.create_phone_booking(PhoneBookingCreate(**data), env.admin, env.db)
    data.update(room_id=env.rooms[1].id, reason="Замена аудитории", event_location="moscow_campus")
    moved = main.transfer_admin_booking(initial["id"], BookingTransferRequest(**data), env.admin, env.db)
    assert {key: moved[key] for key in ANSWERS} == {**ANSWERS, "event_location": "moscow_campus"}


def test_migration_preserves_existing_bookings():
    from importlib import import_module
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine, text

    revision = import_module("migrations.versions.0022_booking_logistics")
    with create_engine("sqlite://").begin() as connection:
        connection.execute(text("CREATE TABLE bookings (id INTEGER PRIMARY KEY, catering_required BOOLEAN, technical_support_required BOOLEAN)"))
        connection.execute(text("INSERT INTO bookings VALUES (1, FALSE, TRUE)"))
        with Operations.context(MigrationContext.configure(connection)):
            revision.upgrade()
        row = connection.execute(text("SELECT * FROM bookings")).mappings().one()
        assert row["id"] == 1 and row["catering_required"] == 0 and row["technical_support_required"] == 1
        assert all(row[key] is None for key in ANSWERS if key != "catering_required")
