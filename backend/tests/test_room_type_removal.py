"""Room classification is removed from storage, API and availability logic."""
from importlib.util import module_from_spec, spec_from_file_location
import inspect
import json
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect as inspect_db, select, text

from app import main
from app.models import Room, Booking
from app.schemas import AvailabilityRequest, RoomCreate
from app.serializers import room_to_dict
from app.services.availability import build_availability
from app.services import bookings
from test_booking_concurrency import race, payload, DAY


def test_schema_model_and_catalog_do_not_expose_room_types():
    assert 'type' not in Room.__table__.columns
    assert not any('type' in index.columns.keys() for index in Room.__table__.indexes)
    assert 'type' not in RoomCreate.model_fields
    assert 'room_type' not in AvailabilityRequest.model_fields
    assert 'type' not in inspect.signature(main.rooms).parameters
    source = json.loads((Path(__file__).resolve().parents[1] / 'app/catalog_data.json').read_text(encoding='utf-8'))
    assert len(source['rooms']) == 117
    assert all('type' not in room for room in source['rooms'])


def test_room_can_be_created_without_classification():
    data = RoomCreate(number='102', name='Аудитория 102', building_id=1, floor=2, capacity=30)
    assert 'type' not in data.model_dump()
    # Old cached clients cannot revive the deleted classification or its filter.
    legacy = RoomCreate(**data.model_dump(), type='lab')
    assert 'type' not in legacy.model_dump()


def test_availability_ignores_removed_filter_and_room_payload_has_no_type(race):
    with race.factory() as db:
        data = build_availability(db, AvailabilityRequest(date=DAY, time_start='10:00', time_end='12:00', room_type='lecture'))
        assert {room['id'] for room in data['free']} == {room.id for room in race.rooms}
        assert all('type' not in room for room in data['free'])
        chosen = db.get(Room, race.rooms[0].id)
        assert room_to_dict(chosen)['equipment'] == []
        assert 'type' not in room_to_dict(chosen)


def test_new_booking_and_room_read_work_without_room_classification(race):
    with race.factory() as db:
        result = bookings.create_booking(db, payload(race), race.admin)
        assert result.status == 'approved'
        assert result.booking_type == 'other'  # event type is a different business field
        assert db.get(Booking, result.id).room_id == race.rooms[0].id
        if race.postgres:
            rooms = main.rooms(db=db)
            assert len(rooms) == 2 and all('type' not in item for item in rooms)


def migration():
    path = Path(__file__).resolve().parents[1] / 'migrations/versions/0019_remove_room_type.py'
    spec = spec_from_file_location('remove_room_classification', path)
    module = module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_room_type_migration_removes_only_classification_and_keeps_bookings(race):
    if not race.postgres:
        pytest.skip('Requires PostgreSQL migration')
    with race.engine.begin() as conn:
        conn.execute(text("ALTER TABLE rooms ADD COLUMN type varchar(50) NOT NULL DEFAULT 'lab'"))
        conn.execute(text('CREATE INDEX ix_rooms_type ON rooms(type)'))
        before = conn.execute(text("SELECT (to_jsonb(r)-'type')::text FROM rooms r ORDER BY id")).scalars().all()
        bookings_before = conn.execute(text('SELECT to_jsonb(b)::text FROM bookings b ORDER BY id')).scalars().all()
        with Operations.context(MigrationContext.configure(conn)):
            migration().upgrade()
        assert 'type' not in {column['name'] for column in inspect_db(conn).get_columns('rooms')}
        assert 'ix_rooms_type' not in {index['name'] for index in inspect_db(conn).get_indexes('rooms')}
        assert conn.execute(text('SELECT to_jsonb(r)::text FROM rooms r ORDER BY id')).scalars().all() == before
        assert conn.execute(text('SELECT to_jsonb(b)::text FROM bookings b ORDER BY id')).scalars().all() == bookings_before
        with Operations.context(MigrationContext.configure(conn)):
            migration().downgrade()
        assert conn.execute(text('SELECT DISTINCT type FROM rooms')).scalars().all() == ['other']
        with Operations.context(MigrationContext.configure(conn)):
            migration().upgrade()
