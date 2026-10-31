"""Database invariant, migration safety, API error translation and concurrency."""
from concurrent.futures import ThreadPoolExecutor
from datetime import time
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app import database
from app.booking_constraints import BOOKING_OVERLAP_CONSTRAINT, BOOKING_OVERLAP_MESSAGE, database_conflict_detail
from app.models import Booking, BookingEvent
from app.services import booking_lifecycle as lifecycle, bookings, operations
from app.schemas import BookingTransferRequest, BatchBookingCreate, ExtraRoomRequest
from test_booking_concurrency import race, payload, DAY


def require_postgres(race):
    if not race.postgres:
        pytest.skip('Requires isolated PostgreSQL schema')


def raw_booking(race, **values):
    data = dict(room_id=race.rooms[0].id, owner_id=race.admin.id, date=DAY,
                time_start=time(10), time_end=time(12), title='Database guard test',
                booked_by='Test administrator', status='approved', record_kind='booking')
    data.update(values)
    return Booking(**data)


@pytest.mark.parametrize('code,constraint,translated', [
    ('23P01', BOOKING_OVERLAP_CONSTRAINT, True),
    ('23P01', 'some_other_constraint', False),
    ('23505', BOOKING_OVERLAP_CONSTRAINT, False),
    ('23514', None, False),
    ('40P01', None, True),
    ('40001', None, True),
])
def test_only_recognized_conflicts_are_translated(code, constraint, translated):
    exc = SimpleNamespace(orig=SimpleNamespace(sqlstate=code, diag=SimpleNamespace(constraint_name=constraint)))
    assert bool(database_conflict_detail(exc)) == translated


@pytest.mark.parametrize('code', ['23P01', '40P01', '40001', '23505'])
def test_dependency_rolls_back_and_closes_failed_transaction(monkeypatch, code):
    calls = []
    monkeypatch.setattr(database, 'SessionLocal', lambda: SimpleNamespace(
        rollback=lambda: calls.append('rollback'), close=lambda: calls.append('close')))
    orig = Exception('Private database details')
    orig.sqlstate = code
    orig.diag = SimpleNamespace(constraint_name=BOOKING_OVERLAP_CONSTRAINT)
    exc = DBAPIError('Private SQL', {}, orig)
    dependency = database.get_db()
    next(dependency)
    if code == '23505':
        with pytest.raises(DBAPIError):
            dependency.throw(exc)
    else:
        with pytest.raises(HTTPException) as caught:
            dependency.throw(exc)
        assert caught.value.status_code == 409
        assert 'Private' not in caught.value.detail
    assert calls == ['rollback', 'close']


@pytest.mark.parametrize('kind', ['booking', 'maintenance', 'setup', 'teardown', 'unavailable'])
def test_direct_database_write_cannot_bypass_occupancy_check(race, kind):
    require_postgres(race)
    with race.factory() as db:
        db.add(raw_booking(race)); db.commit()
        db.add(raw_booking(race, record_kind=kind, time_start=time(11), time_end=time(13)))
        db.flush()  # Deferred: intermediate state can exist only inside this transaction.
        with pytest.raises(IntegrityError) as caught:
            db.commit()
        assert database_conflict_detail(caught.value) == BOOKING_OVERLAP_MESSAGE
        db.rollback()
        assert db.scalar(select(func.count()).select_from(Booking).where(Booking.status == 'approved')) == 1


def test_neighbors_other_rooms_and_other_dates_remain_allowed(race):
    require_postgres(race)
    from datetime import timedelta
    with race.factory() as db:
        db.add_all([raw_booking(race), raw_booking(race, time_start=time(12), time_end=time(13)),
                    raw_booking(race, time_start=time(9), time_end=time(10)),
                    raw_booking(race, room_id=race.rooms[1].id), raw_booking(race, date=DAY + timedelta(days=1))])
        db.commit()
        assert db.scalar(select(func.count()).select_from(Booking).where(Booking.status == 'approved')) == 5


@pytest.mark.parametrize('status', ['pending', 'rejected', 'cancelled', 'cancelled_by_user', 'cancelled_by_admin', 'completed', 'no_show', 'transferred'])
def test_non_blocking_statuses_do_not_reserve_room(race, status):
    require_postgres(race)
    with race.factory() as db:
        db.add_all([raw_booking(race), raw_booking(race, status=status), raw_booking(race, status=status)])
        db.commit()


def test_status_change_is_guarded_and_cancellation_releases_room(race):
    require_postgres(race)
    with race.factory() as db:
        first, second = raw_booking(race), raw_booking(race, status='pending')
        db.add_all([first, second]); db.commit()
        first_id, second_id = first.id, second.id
        second.status = 'approved'
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.get(Booking, first_id).status = 'cancelled_by_admin'
        db.get(Booking, second_id).status = 'approved'
        db.commit()
        assert db.get(Booking, second_id).status == 'approved'


def test_atomic_transfer_to_same_room_and_overlapping_time_still_works(race):
    require_postgres(race)
    with race.factory() as db:
        original = bookings.create_booking(db, payload(race), race.admin)
        new_payload = payload(race).model_dump()
        new_payload.update(time_start='11:00', time_end='13:00')
        replacement = operations.transfer_booking(db, original, BookingTransferRequest(**new_payload, reason='Changed time'), race.admin)
        assert replacement.status == 'approved'
        assert original.status == 'transferred'
        assert replacement.previous_booking_id == original.id


@pytest.mark.parametrize('action', ['create', 'approve', 'series', 'extra'])
def test_api_dependency_reports_conflict_even_if_application_check_is_bypassed(race, monkeypatch, action):
    require_postgres(race)
    from app.services import room_sets
    with race.factory() as db:
        existing = raw_booking(race)
        db.add(existing); db.commit()
    monkeypatch.setattr(bookings, 'find_conflict', lambda *a, **kw: None)
    monkeypatch.setattr(lifecycle, 'find_conflict', lambda *a, **kw: None)
    monkeypatch.setattr(operations, 'find_conflict', lambda *a, **kw: None)
    monkeypatch.setattr(room_sets, 'find_conflict', lambda *a, **kw: None)
    monkeypatch.setattr(bookings, 'reject_competing_requests', lambda *a, **kw: 0)
    monkeypatch.setattr(lifecycle, 'reject_competing_requests', lambda *a, **kw: 0)
    monkeypatch.setattr(operations, 'reject_competing_requests', lambda *a, **kw: 0)
    monkeypatch.setattr(room_sets, 'reject_competing_requests', lambda *a, **kw: 0)
    monkeypatch.setattr(database, 'SessionLocal', race.factory)
    dependency = database.get_db()
    db = next(dependency)
    try:
        if action == 'create':
            bookings.create_booking(db, payload(race), race.admin)
        elif action == 'approve':
            lifecycle.transition_booking_status(db, db.get(Booking, race.booking_id), race.admin, 'approved')
        elif action == 'series':
            data = payload(race).model_dump()
            data.pop('room_id'); data.pop('extra_rooms')
            operations.create_series(db, BatchBookingCreate(**data, room_ids=[race.rooms[0].id], date_end=DAY), race.admin)
        else:
            main = bookings.create_booking(db, payload(race, room=1), race.admin)
            room_sets.create_extra_rooms(db, main, [ExtraRoomRequest(room_id=race.rooms[0].id, purpose='Staff')], race.admin)
            db.commit()
    except DBAPIError as exc:
        with pytest.raises(HTTPException) as caught:
            dependency.throw(exc)
        assert caught.value.status_code == 409
        assert caught.value.detail == BOOKING_OVERLAP_MESSAGE
    else:
        pytest.fail('Expected database-level exclusion to reject conflicting approval')
    finally:
        dependency.close()
    with race.factory() as check:
        assert check.get(Booking, race.booking_id).status == 'pending'
        assert check.scalar(select(func.count()).select_from(Booking).where(Booking.status == 'approved')) == (2 if action == 'extra' else 1)


def test_two_concurrent_database_writers_cannot_both_commit(race):
    require_postgres(race)
    ready = Barrier(2)
    def writer(index):
        with race.factory() as db:
            db.execute(text("SET LOCAL statement_timeout = '15s'"))
            db.add(raw_booking(race, title=f'Concurrent writer {index}'))
            db.flush()
            ready.wait(timeout=10)
            try:
                db.commit()
                return 'approved'
            except DBAPIError as exc:
                detail = database_conflict_detail(exc)
                db.rollback()
                assert detail, f'Unexpected database error {getattr(exc.orig, "sqlstate", None)}'
                return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(writer, range(2)))
    assert sorted(outcomes) == ['approved', 'conflict']
    with race.factory() as db:
        assert db.scalar(select(func.count()).select_from(Booking).where(Booking.status == 'approved')) == 1


def migration_module():
    path = Path(__file__).resolve().parents[1] / 'migrations/versions/0015_booking_no_overlap.py'
    spec = spec_from_file_location('migration_no_overlap', path)
    module = module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_migration_upgrade_downgrade_preserves_booking_data(race):
    require_postgres(race)
    migration = migration_module()
    with race.engine.begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            migration.downgrade()
            before = conn.execute(text('SELECT to_jsonb(b) FROM bookings b ORDER BY id')).scalars().all()
            migration.upgrade()
            after = conn.execute(text('SELECT to_jsonb(b) FROM bookings b ORDER BY id')).scalars().all()
            assert before == after
        state = conn.execute(text("SELECT condeferrable,condeferred FROM pg_constraint WHERE conrelid='bookings'::regclass AND conname=:name"), {'name': BOOKING_OVERLAP_CONSTRAINT}).one()
        assert tuple(state) == (True, True)


def test_migration_refuses_existing_conflicts_without_deleting_them(race):
    require_postgres(race)
    migration = migration_module()
    with race.engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()
    with race.factory() as db:
        db.add_all([raw_booking(race), raw_booking(race)]); db.commit()
    with pytest.raises(IntegrityError):
        with race.engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
    with race.factory() as db:
        assert db.scalar(select(func.count()).select_from(Booking).where(Booking.status == 'approved')) == 2
