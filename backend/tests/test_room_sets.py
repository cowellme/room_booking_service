"""Sets of rooms: a main booking with extra rooms (staff room, storage, …) booked in one request."""
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.models import Base, Booking, Building, Room, User
from app.schemas import (BookingCancelRequest, BookingCreate, BookingTransferRequest, BookingUpdate, ExtraRoomRequest,
                         ExtraRoomsAdd)
from app.services import analytics, booking_lifecycle as lifecycle, bookings as bookings_service, operations

NOW = datetime(2029, 12, 20, 9, 0)
DAY = date(2030, 1, 14)
CANCEL = BookingCancelRequest(reason="Изменились планы", comment="Тест")


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    event.listen(engine, "connect", lambda conn, _: conn.create_function("pg_advisory_xact_lock", 1, lambda key: None))
    Base.metadata.create_all(engine)
    db = sessionmaker(engine, expire_on_commit=False)()
    clock = SimpleNamespace(now=NOW)
    for module in (lifecycle, bookings_service, main, analytics):
        monkeypatch.setattr(module, "local_now", lambda: clock.now)
    building = Building(name="Корпус 1"); db.add(building); db.flush()
    rooms = [Room(number=str(100 + i), name=f"Ауд {i}", building_id=building.id, capacity=30) for i in range(5)]
    users = {n: User(email=f"{n}@t.ru", full_name=n, password_hash="x", role="admin" if n == "admin" else "user")
             for n in ("admin", "anna", "boris")}
    db.add_all(rooms + list(users.values())); db.commit()
    yield SimpleNamespace(db=db, clock=clock, rooms=rooms, **users)
    db.close()


def extra(env, index, purpose="Штаб", start=None, end=None):
    return ExtraRoomRequest(room_id=env.rooms[index].id, purpose=purpose, time_start=start, time_end=end)


def book(env, user, *, room=0, extras=(), start="10:00", end="12:00"):
    payload = BookingCreate(catering_required=False, technical_support_required=False, room_id=env.rooms[room].id, date=DAY, time_start=start, time_end=end, title="Конференция",
                            participants=10, extra_rooms=list(extras))
    return bookings_service.create_booking(env.db, payload, user)


def children(env, item):
    return list(env.db.scalars(select(Booking).where(Booking.parent_booking_id == item.id).order_by(Booking.id)))


def approve(env, item):
    lifecycle.transition_booking_status(env.db, item, env.admin, "approved")


def test_user_set_is_created_as_one_pending_request(env):
    main_item = book(env, env.anna, extras=[extra(env, 1, "Штаб"), extra(env, 2, "Хранение вещей", "08:00", "13:00")])
    extras = children(env, main_item)
    assert [e.status for e in extras] == ["pending", "pending"]
    assert extras[0].time_start == time(10) and extras[1].time_start == time(8) and extras[1].time_end == time(13)
    assert extras[1].room_purpose == "Хранение вещей" and extras[1].title == "Конференция — Хранение вещей"
    assert all(e.date == DAY and e.owner_id == env.anna.id and e.participants is None for e in extras)


def test_admin_set_is_approved_at_once(env):
    main_item = book(env, env.admin, extras=[extra(env, 1)])
    assert main_item.status == "approved" and children(env, main_item)[0].status == "approved"


def test_busy_extra_room_blocks_whole_request(env):
    book(env, env.admin, room=1)
    with pytest.raises(HTTPException) as error:
        book(env, env.anna, extras=[extra(env, 2), extra(env, 1)])
    assert error.value.status_code == 409 and "101" in error.value.detail
    assert env.db.scalars(select(Booking).where(Booking.owner_id == env.anna.id)).all() == []


@pytest.mark.parametrize("extras,code", [
    (lambda env: [extra(env, 0)], 409),               # the main room again
    (lambda env: [extra(env, 1), extra(env, 1)], 409),  # the same room twice
    (lambda env: [extra(env, 1, start="07:00", end="09:00")], 400),  # outside working hours
])
def test_invalid_extras(env, extras, code):
    with pytest.raises(HTTPException) as error:
        book(env, env.anna, extras=extras(env))
    assert error.value.status_code == code
    assert env.db.scalars(select(Booking)).all() == []


def test_set_is_approved_together(env):
    main_item = book(env, env.anna, extras=[extra(env, 1), extra(env, 2)])
    approve(env, main_item)
    assert {e.status for e in children(env, main_item)} == {"approved"}


def test_extra_cannot_be_approved_alone_while_main_pending(env):
    main_item = book(env, env.anna, extras=[extra(env, 1)])
    with pytest.raises(HTTPException) as error:
        approve(env, children(env, main_item)[0])
    assert error.value.status_code == 409


def test_busy_extra_blocks_approval_until_removed(env):
    main_item = book(env, env.anna, extras=[extra(env, 1, "Штаб"), extra(env, 2, "Склад")])
    other = book(env, env.boris, room=2)
    approve(env, other)  # takes room 102 and rejects the competing extra room automatically
    staff, storage = children(env, main_item)
    assert storage.status == "rejected"
    approve(env, main_item)
    assert staff.status == "approved"


def test_conflicting_extra_must_be_removed_first(env):
    main_item = book(env, env.anna, extras=[extra(env, 1, "Штаб"), extra(env, 2, "Склад")])
    staff, storage = children(env, main_item)
    # Room 102 got taken by a record that does not reject competitors (e.g. admin edit of an old booking).
    env.db.add(Booking(room_id=env.rooms[2].id, owner_id=env.admin.id, date=DAY, time_start=time(9), time_end=time(11),
                       title="Ремонт", booked_by="admin", status="approved")); env.db.commit()
    with pytest.raises(HTTPException) as error:
        approve(env, main_item)
    assert error.value.status_code == 409 and "102" in error.value.detail
    assert main_item.status == "pending"
    lifecycle.transition_booking_status(env.db, storage, env.admin, "rejected", "Снята из комплекта: аудитория занята")
    approve(env, main_item)
    assert (main_item.status, staff.status, storage.status) == ("approved", "approved", "rejected")


def test_rejecting_main_rejects_set(env):
    main_item = book(env, env.anna, extras=[extra(env, 1)])
    lifecycle.transition_booking_status(env.db, main_item, env.admin, "rejected", "Нет возможности")
    extra_item = children(env, main_item)[0]
    assert extra_item.status == "rejected" and extra_item.decision_reason == "Нет возможности"


def test_cancel_main_cancels_set_but_extra_can_be_cancelled_alone(env):
    main_item = book(env, env.admin, extras=[extra(env, 1), extra(env, 2)])
    first, second = children(env, main_item)
    lifecycle.cancel_booking_record(env.db, first, env.admin, reason="r", comment="c", replacement_offered=False, notify_customer=False)
    assert (main_item.status, first.status, second.status) == ("approved", "cancelled_by_admin", "approved")
    lifecycle.cancel_booking_record(env.db, main_item, env.admin, reason="r", comment="c", replacement_offered=False, notify_customer=False)
    assert second.status == "cancelled_by_admin"


def test_transfer_moves_extras_to_new_date(env):
    main_item = book(env, env.admin, extras=[extra(env, 1)])
    moved = operations.transfer_booking(env.db, main_item, BookingTransferRequest(catering_required=False, technical_support_required=False, 
        room_id=env.rooms[0].id, date=DAY + timedelta(days=1), time_start="10:00", time_end="12:00",
        title="Конференция", reason="Перенос"), env.admin)
    extra_item = children(env, moved)[0]
    assert extra_item.date == DAY + timedelta(days=1) and extra_item.status == "approved"


def test_transfer_blocked_when_extra_busy_on_new_date(env):
    main_item = book(env, env.admin, extras=[extra(env, 1)])
    env.db.add(Booking(room_id=env.rooms[1].id, owner_id=env.admin.id, date=DAY + timedelta(days=1), time_start=time(10),
                       time_end=time(11), title="Другое", booked_by="admin", status="approved")); env.db.commit()
    with pytest.raises(HTTPException) as error:
        operations.transfer_booking(env.db, main_item, BookingTransferRequest(catering_required=False, technical_support_required=False, 
            room_id=env.rooms[0].id, date=DAY + timedelta(days=1), time_start="10:00", time_end="12:00",
            title="Конференция", reason="Перенос"), env.admin)
    assert error.value.status_code == 409
    env.db.refresh(main_item)
    assert main_item.status == "approved" and children(env, main_item)[0].date == DAY


def test_extra_cannot_be_transferred_alone(env):
    main_item = book(env, env.admin, extras=[extra(env, 1)])
    with pytest.raises(HTTPException):
        operations.transfer_booking(env.db, children(env, main_item)[0], BookingTransferRequest(catering_required=False, technical_support_required=False, 
            room_id=env.rooms[3].id, date=DAY, time_start="10:00", time_end="12:00", title="Штаб", reason="Перенос"), env.admin)


def test_add_extra_later(env):
    main_item = book(env, env.anna)
    approve(env, main_item)
    added = main.add_my_extra_rooms(main_item.id, ExtraRoomsAdd(extra_rooms=[extra(env, 3, "Гардероб")]), env.anna, env.db)
    assert added[0]["status"] == "pending" and added[0]["parent_booking_id"] == main_item.id
    approve(env, env.db.get(Booking, added[0]["id"]))  # main is approved, so the extra is decided on its own
    added = main.add_admin_extra_rooms(main_item.id, ExtraRoomsAdd(extra_rooms=[extra(env, 4, "Питание")]), env.admin, env.db)
    assert added[0]["status"] == "approved"
    with pytest.raises(HTTPException):
        main.add_my_extra_rooms(main_item.id, ExtraRoomsAdd(extra_rooms=[extra(env, 2)]), env.boris, env.db)


def test_admin_moving_main_date_moves_extras(env):
    main_item = book(env, env.admin, extras=[extra(env, 1)])
    main.update_admin_booking(main_item.id, BookingUpdate(date=DAY + timedelta(days=2)), env.admin, env.db)
    assert children(env, main_item)[0].date == DAY + timedelta(days=2)
    with pytest.raises(HTTPException):
        main.update_admin_booking(children(env, main_item)[0].id, BookingUpdate(date=DAY), env.admin, env.db)


def test_delete_main_deletes_extras(env):
    main_item = book(env, env.admin, extras=[extra(env, 1)])
    lifecycle.delete_booking_record(env.db, main_item)
    assert env.db.scalars(select(Booking)).all() == []


def test_analytics_counts_set_as_one_request(env):
    book(env, env.anna, extras=[extra(env, 1), extra(env, 2)])
    requests = analytics._requests(env.db)
    assert len(requests) == 1 and requests[0].first.parent_booking_id is None


def test_set_decision_is_one_notification(env):
    main_item = book(env, env.anna, extras=[extra(env, 1), extra(env, 2)])
    approve(env, main_item)
    notes = main.my_notifications(0, env.anna, env.db)
    assert len(notes) == 1 and "комплект, аудиторий: 3" in notes[0]["summary"]
