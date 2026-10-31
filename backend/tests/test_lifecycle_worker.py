"""Read-only pages and independent, recoverable, multi-process-safe lifecycle work."""
import ast
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text

from app import main
from app.models import Booking, BookingEvent
from app.services import booking_lifecycle as lifecycle, bookings, lifecycle_worker as worker
from test_booking_concurrency import race, payload, DAY


def due_records(race):
    with race.factory() as db:
        approved = bookings.create_booking(db, payload(race, room=1), race.admin)
        ids = race.booking_id, approved.id
    race.clock.now = datetime(2030, 1, 14, 12, 30)
    return ids


def states(race, ids):
    with race.factory() as db:
        return {item.id: item.status for item in db.scalars(select(Booking).where(Booking.id.in_(ids)))}


@pytest.mark.parametrize('page', ['calendar', 'mine', 'notifications', 'analytics', 'booking_center', 'moderation'])
def test_page_reads_work_in_read_only_transaction_and_do_not_change_due_records(race, monkeypatch, page):
    ids = due_records(race)
    with race.factory() as db:
        if race.postgres:
            db.execute(text('SET TRANSACTION READ ONLY'))
        def no_commit():
            pytest.fail('A read-only page attempted to commit')
        monkeypatch.setattr(db, 'commit', no_commit)
        calls = {
            'calendar': lambda: main.bookings(DAY, DAY, user=race.admin, db=db),
            'mine': lambda: main.my_bookings(user=race.user, db=db),
            'notifications': lambda: main.my_notifications(user=race.user, db=db),
            'analytics': lambda: main.admin_analytics(DAY, DAY + timedelta(days=1), _=race.admin, db=db),
            'booking_center': lambda: main.booking_center(user=race.admin, db=db),
            'moderation': lambda: main.moderation(user=race.admin, db=db),
        }
        calls[page]()
        assert not db.new and not db.dirty and not db.deleted
    assert states(race, ids) == {ids[0]: 'pending', ids[1]: 'approved'}


def test_automatic_processor_is_not_called_by_http_handlers_or_commands():
    tree = ast.parse(Path(main.__file__).read_text(encoding='utf-8'))
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id == 'expire_pending_requests' for node in ast.walk(tree))
    tree = ast.parse(Path(lifecycle.__file__).read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name != 'expire_pending_requests':
            assert not any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                           and call.func.id == 'expire_pending_requests' for call in ast.walk(node))


def test_worker_processes_due_records_without_any_page_views_and_is_idempotent(race):
    ids = due_records(race)
    result = worker.run_lifecycle_once(race.factory)
    assert result == {'ran': True, 'expired': 1}
    assert states(race, ids) == {ids[0]: 'rejected', ids[1]: 'completed'}
    assert worker.run_lifecycle_once(race.factory) == {'ran': True, 'expired': 0}
    with race.factory() as db:
        for booking_id, expected in [(ids[0], 'expired'), (ids[1], 'completed')]:
            events = db.scalars(select(BookingEvent).where(BookingEvent.booking_id == booking_id, BookingEvent.event_type == expected)).all()
            assert len(events) == 1 and events[0].data['system'] is True
        notifications = main.my_notifications(user=race.user, db=db)
        assert len([n for n in notifications if n['type'] == 'expired' and n['booking_id'] == ids[0]]) == 1


def test_command_on_one_booking_does_not_process_other_due_records(race):
    ids = due_records(race)
    with race.factory() as db:
        with pytest.raises(HTTPException) as caught:
            lifecycle.transition_booking_status(db, db.get(Booking, ids[0]), race.admin, 'approved')
        assert caught.value.status_code == 409
    assert states(race, ids) == {ids[0]: 'pending', ids[1]: 'approved'}


def test_worker_rolls_back_entire_cycle_on_error_and_next_cycle_recovers(race, monkeypatch):
    ids = due_records(race)
    original = lifecycle.record_event
    def fail_on_completion(db, booking, actor, kind, summary, data=None):
        if kind == 'completed':
            raise RuntimeError('Simulated audit write failure')
        return original(db, booking, actor, kind, summary, data)
    monkeypatch.setattr(lifecycle, 'record_event', fail_on_completion)
    with pytest.raises(RuntimeError):
        worker.run_lifecycle_once(race.factory)
    assert states(race, ids) == {ids[0]: 'pending', ids[1]: 'approved'}
    with race.factory() as db:
        assert db.scalar(select(func.count()).select_from(BookingEvent).where(BookingEvent.event_type.in_(['expired', 'completed']))) == 0
    monkeypatch.setattr(lifecycle, 'record_event', original)
    assert worker.run_lifecycle_once(race.factory)['ran'] is True
    assert states(race, ids) == {ids[0]: 'rejected', ids[1]: 'completed'}


def test_postgres_only_one_worker_owns_cycle_and_next_worker_can_take_over(race):
    if not race.postgres:
        pytest.skip('Requires PostgreSQL advisory locks')
    ids = due_records(race)
    with race.factory() as holder:
        holder.execute(text('SELECT pg_advisory_xact_lock(:namespace, :key)'),
                       {'namespace': worker.LIFECYCLE_LOCK_NAMESPACE, 'key': worker.LIFECYCLE_LOCK_KEY})
        assert worker.run_lifecycle_once(race.factory) == {'ran': False, 'expired': 0}
        assert states(race, ids) == {ids[0]: 'pending', ids[1]: 'approved'}
        holder.rollback()
    assert worker.run_lifecycle_once(race.factory)['ran'] is True
    assert states(race, ids) == {ids[0]: 'rejected', ids[1]: 'completed'}


def test_worker_retries_locked_booking_on_next_cycle(race):
    if not race.postgres:
        pytest.skip('Requires PostgreSQL row locks')
    ids = due_records(race)
    with race.factory() as decision:
        decision.execute(select(Booking).where(Booking.id == ids[0]).with_for_update())
        assert worker.run_lifecycle_once(race.factory)['expired'] == 0
        assert states(race, ids) == {ids[0]: 'pending', ids[1]: 'completed'}
        decision.rollback()
    assert worker.run_lifecycle_once(race.factory)['expired'] == 1
    assert states(race, ids) == {ids[0]: 'rejected', ids[1]: 'completed'}


def test_periodic_loop_recovers_from_failure_and_stops_cleanly(caplog):
    calls = []
    async def scenario():
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        def cycle():
            calls.append('cycle')
            if len(calls) == 1:
                raise RuntimeError('Temporary database outage')
            loop.call_soon_threadsafe(stop.set)
            return {'ran': True, 'expired': 0}
        await asyncio.wait_for(worker.lifecycle_loop(stop, .01, cycle), timeout=3)
    asyncio.run(scenario())
    assert calls == ['cycle', 'cycle']
    assert 'retrying after the interval' in caplog.text


def test_stopped_loop_does_not_start_database_work():
    calls = []
    async def scenario():
        stop = asyncio.Event(); stop.set()
        await worker.lifecycle_loop(stop, .01, lambda: calls.append('unexpected'))
    asyncio.run(scenario())
    assert calls == []


def test_shutdown_waits_for_current_database_cycle():
    entered, release, finished = Event(), Event(), Event()
    async def scenario():
        stop = asyncio.Event()
        def cycle():
            entered.set()
            assert release.wait(3)
            finished.set()
            return {'ran': True, 'expired': 0}
        task = asyncio.create_task(worker.lifecycle_loop(stop, 30, cycle))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            stop.set()
            await asyncio.sleep(.01)
            assert not task.done()
        finally:
            release.set()
        await asyncio.wait_for(task, timeout=3)
    asyncio.run(scenario())
    assert finished.is_set()


@pytest.mark.parametrize('enabled', [False, True])
def test_application_lifespan_starts_and_stops_configured_worker(monkeypatch, enabled):
    calls = []
    async def fake_loop(stop, interval):
        calls.append(('start', interval))
        await stop.wait()
        calls.append(('stop', interval))
    monkeypatch.setattr(main, 'settings', replace(main.settings, lifecycle_worker_enabled=enabled, lifecycle_interval_seconds=42))
    monkeypatch.setattr(main, 'lifecycle_loop', fake_loop)
    async def scenario():
        async with main.lifespan(main.app):
            await asyncio.sleep(0)
            assert bool(calls) == enabled
    asyncio.run(scenario())
    assert calls == ([('start', 42), ('stop', 42)] if enabled else [])
