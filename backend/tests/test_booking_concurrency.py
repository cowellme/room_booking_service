"""Stale-state regressions and real PostgreSQL locking checks.

Default: isolated SQLite file (stale ORM state regressions).
BOOKING_CONCURRENCY_TEST_URL: PostgreSQL, each test in its own temporary schema.
Never uses or changes public/production tables.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time
from threading import Event
from types import SimpleNamespace
import os
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select, text, update, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from app import main
from app.models import Base, Booking, BookingEvent, Building, Room, User
from app.schemas import BookingCreate, BookingTransferRequest, BookingUpdate, ExtraRoomRequest
from app.services import booking_lifecycle as lifecycle, bookings, operations, booking_locks, room_sets

DAY = date(2030, 1, 14)


@pytest.fixture
def race(monkeypatch, tmp_path):
    url = os.environ.get('BOOKING_CONCURRENCY_TEST_URL')
    admin_engine = None
    schema = None
    if url:
        admin_engine = create_engine(url)
        schema = 'booking_race_' + uuid.uuid4().hex
        with admin_engine.begin() as conn:
            conn.execute(CreateSchema(schema))
        engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
    else:
        engine = create_engine('sqlite:///' + str(tmp_path / 'race.sqlite'))
        event.listen(engine, 'connect', lambda conn, _: conn.create_function('pg_advisory_xact_lock', 1, lambda key: None))
    factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    clock = SimpleNamespace(now=datetime(2029, 12, 20, 9))
    for module in (main, lifecycle, bookings):
        monkeypatch.setattr(module, 'local_now', lambda: clock.now)
    try:
        Base.metadata.create_all(engine)
        with factory() as db:
            building = Building(name='Concurrency test')
            db.add(building); db.flush()
            rooms = [Room(number=str(i), name=f'Room {i}', building_id=building.id, capacity=30) for i in (1, 2)]
            users = [User(email=f'{role}@test.local', full_name=role, role=role, password_hash='test') for role in ('admin', 'user')]
            db.add_all(rooms + users); db.commit()
            env = SimpleNamespace(factory=factory, engine=engine, rooms=rooms, admin=users[0], user=users[1], clock=clock, postgres=bool(url))
            item = bookings.create_booking(db, payload(env), env.user)
            env.booking_id = item.id
        yield env
    finally:
        engine.dispose()
        if admin_engine:
            try:
                with admin_engine.begin() as conn:
                    conn.execute(DropSchema(schema, cascade=True))
            finally:
                admin_engine.dispose()


def payload(env, room=0):
    return BookingCreate(catering_required=False, technical_support_required=False, room_id=env.rooms[room].id, date=DAY, time_start='10:00', time_end='12:00', title='Test event', participants=10)


def cancel(db, item, actor):
    lifecycle.cancel_booking_record(db, item, actor, reason='Changed plans', comment='Test', replacement_offered=False, notify_customer=False)


def expect_conflict(call):
    with pytest.raises(HTTPException) as exc:
        call()
    assert exc.value.status_code == 409


def test_cancelled_request_is_not_resurrected_by_stale_approval(race):
    with race.factory() as first, race.factory() as second:
        stale = first.get(Booking, race.booking_id)
        cancel(second, second.get(Booking, stale.id), race.user)
        expect_conflict(lambda: lifecycle.transition_booking_status(first, stale, race.admin, 'approved'))
    with race.factory() as check:
        item = check.get(Booking, race.booking_id)
        assert item.status == 'cancelled_by_user'
        assert item.cancellation_reason == 'Changed plans'
        assert check.scalar(select(func.count()).select_from(BookingEvent).where(BookingEvent.event_type == 'approved')) == 0


def test_changed_room_is_not_approved_against_old_room(race):
    with race.factory() as first, race.factory() as second:
        stale = first.get(Booking, race.booking_id)
        bookings.create_booking(second, payload(race, room=1), race.admin)
        second.execute(update(Booking).where(Booking.id == stale.id).values(room_id=race.rooms[1].id))
        second.commit()
        expect_conflict(lambda: lifecycle.transition_booking_status(first, stale, race.admin, 'approved'))
    with race.factory() as check:
        assert check.get(Booking, race.booking_id).status == 'pending'
        assert check.scalar(select(func.count()).select_from(Booking).where(Booking.status == 'approved')) == 1


@pytest.mark.parametrize('field,value', [('date', date(2030, 1, 15)), ('time_start', time(11)), ('time_end', time(13)), ('participants', 20)])
def test_stale_schedule_and_participants_require_retry(race, field, value):
    with race.factory() as first, race.factory() as second:
        stale = first.get(Booking, race.booking_id)
        second.execute(update(Booking).where(Booking.id == stale.id).values(**{field: value}))
        second.commit()
        expect_conflict(lambda: lifecycle.transition_booking_status(first, stale, race.admin, 'approved'))


@pytest.mark.parametrize('action', ['edit', 'transfer'])
def test_stale_edit_or_transfer_cannot_overwrite_cancellation(race, action):
    with race.factory() as first, race.factory() as second:
        stale = first.get(Booking, race.booking_id)
        cancel(second, second.get(Booking, stale.id), race.user)
        if action == 'edit':
            expect_conflict(lambda: main.update_admin_booking(stale.id, BookingUpdate(title='Updated title'), race.admin, first))
        else:
            transfer = BookingTransferRequest(**payload(race, room=1).model_dump(), reason='Other room')
            expect_conflict(lambda: operations.transfer_booking(first, stale, transfer, race.admin))
    with race.factory() as check:
        assert check.get(Booking, race.booking_id).status == 'cancelled_by_user'
        assert check.scalar(select(func.count()).select_from(Booking)) == 1


def test_competing_rejection_refreshes_cached_booking(race):
    with race.factory() as first, race.factory() as second:
        cached = first.get(Booking, race.booking_id)
        second.execute(update(Booking).where(Booking.id == cached.id).values(title='Changed title'))
        second.commit()
        bookings.create_booking(first, payload(race), race.admin)
        assert cached.status == 'rejected'
        assert cached.title == 'Changed title'


@pytest.mark.parametrize('action', ['approve', 'cancel', 'edit', 'transfer', 'series', 'extra'])
def test_postgres_busy_request_returns_conflict_without_partial_write(race, action):
    if not race.postgres:
        pytest.skip('Requires isolated PostgreSQL schema')
    with race.factory() as holder, race.factory() as contender:
        held = holder.get(Booking, race.booking_id)
        if action == 'series':
            held.series_id = 'test-series'; holder.commit()
        booking_locks.lock_booking_record(holder, held)
        item = contender.get(Booking, held.id)
        actions = {
            'approve': lambda: lifecycle.transition_booking_status(contender, item, race.admin, 'approved'),
            'cancel': lambda: cancel(contender, item, race.user),
            'edit': lambda: main.update_admin_booking(item.id, BookingUpdate(title='Changed title'), race.admin, contender),
            'transfer': lambda: operations.transfer_booking(contender, item, BookingTransferRequest(**payload(race, room=1).model_dump(), reason='Other room'), race.admin),
            'series': lambda: lifecycle.transition_series_status(contender, 'test-series', race.admin, 'approved'),
            'extra': lambda: room_sets.create_extra_rooms(contender, item, [ExtraRoomRequest(room_id=race.rooms[1].id, purpose='Staff room')], race.user),
        }
        expect_conflict(actions[action])
        holder.rollback()
    with race.factory() as check:
        assert check.get(Booking, race.booking_id).status == 'pending'
        assert check.scalar(select(func.count()).select_from(Booking)) == 1


def test_postgres_competing_rejection_does_not_deadlock_or_leave_partial_booking(race):
    if not race.postgres:
        pytest.skip('Requires isolated PostgreSQL schema')
    with race.factory() as holder, race.factory() as creator:
        booking_locks.lock_booking_record(holder, holder.get(Booking, race.booking_id))
        expect_conflict(lambda: bookings.create_booking(creator, payload(race), race.admin))
        holder.rollback()
        assert bookings.create_booking(creator, payload(race), race.admin).status == 'approved'
    with race.factory() as check:
        assert check.get(Booking, race.booking_id).status == 'rejected'
        assert check.scalar(select(func.count()).select_from(Booking)) == 2


def test_postgres_expiry_skips_in_progress_decision(race):
    if not race.postgres:
        pytest.skip('Requires isolated PostgreSQL schema')
    with race.factory() as holder, race.factory() as reader:
        booking_locks.lock_booking_record(holder, holder.get(Booking, race.booking_id))
        race.clock.now = datetime(2030, 1, 14, 10, 30)
        assert lifecycle.expire_pending_requests(reader) == 0
        holder.rollback()
        assert lifecycle.expire_pending_requests(reader) == 1


def test_postgres_approval_holds_request_while_waiting_for_room(race):
    if not race.postgres:
        pytest.skip('Requires isolated PostgreSQL schema')
    waiting = Event()
    def watch(conn, cursor, statement, parameters, context, executemany):
        if 'pg_advisory_xact_lock' in statement:
            waiting.set()
    with race.factory() as holder:
        key = DAY.toordinal() * 100000 + race.rooms[0].id
        holder.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})
        event.listen(race.engine, 'before_cursor_execute', watch)
        def approve():
            with race.factory() as db:
                lifecycle.transition_booking_status(db, db.get(Booking, race.booking_id), race.admin, 'approved')
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(approve)
            try:
                assert waiting.wait(10), 'Approval did not reach room lock'
                with race.factory() as db:
                    expect_conflict(lambda: cancel(db, db.get(Booking, race.booking_id), race.user))
            finally:
                holder.rollback()
            future.result(timeout=10)
        event.remove(race.engine, 'before_cursor_execute', watch)
    with race.factory() as check:
        assert check.get(Booking, race.booking_id).status == 'approved'
