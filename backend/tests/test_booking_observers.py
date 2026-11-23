"""Observer access is read-only and isolated from the booking owner workflow."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import main
from app.models import Booking, BookingComment, BookingObserver, User
from app.schemas import BookingCommentCreate, BookingObserversUpdate
from tests.test_audit_fixes import book, env  # noqa: F401


def _booking(env) -> Booking:
    created = book(env, env.anna, customer_name="Анна", department_name="Центр программ", external_reference="ВШГУ-OBS-1")
    return created


def test_admin_assigns_and_removes_observer(env):
    observer = User(email="observer@test.ru", full_name="Наталия Волкович", password_hash="x", role="user")
    env.db.add(observer); env.db.commit()
    booking = _booking(env)
    result = main.update_booking_observers(booking.id, BookingObserversUpdate(user_ids=[observer.id]), env.admin, env.db)
    assert [item["id"] for item in result["observers"]] == [observer.id]
    assert env.db.query(BookingObserver).filter_by(booking_id=booking.id).count() == 1
    assert main.booking_center_detail(booking.id, env.admin, env.db)["observers"][0]["email"] == "observer@test.ru"
    main.update_booking_observers(booking.id, BookingObserversUpdate(user_ids=[]), env.admin, env.db)
    assert env.db.query(BookingObserver).filter_by(booking_id=booking.id).count() == 0


def test_observer_sees_full_detail_and_can_comment_but_outsider_cannot(env):
    observer = User(email="observer@test.ru", full_name="Гусейн Абдуллаев", password_hash="x", role="user")
    outsider = User(email="outsider@test.ru", full_name="Посторонний", password_hash="x", role="user")
    env.db.add_all([observer, outsider]); env.db.commit()
    booking = _booking(env)
    main.update_booking_observers(booking.id, BookingObserversUpdate(user_ids=[observer.id]), env.admin, env.db)
    assert [item["id"] for item in main.observed_bookings(observer, env.db)] == [booking.id]
    detail = main.observed_booking_detail(booking.id, observer, env.db)
    assert detail["external_reference"] == "ВШГУ-OBS-1"
    assert "events" in detail and "comments" in detail
    comment = main.add_observer_comment(booking.id, BookingCommentCreate(text="Проверил документы"), observer, env.db)
    assert comment["author"] == "Гусейн Абдуллаев"
    assert env.db.query(BookingComment).filter_by(booking_id=booking.id).one().text == "Проверил документы"
    with pytest.raises(HTTPException) as exc:
        main.observed_booking_detail(booking.id, outsider, env.db)
    assert exc.value.status_code == 404


def test_observer_limit_is_five():
    with pytest.raises(ValidationError):
        BookingObserversUpdate(user_ids=[1, 2, 3, 4, 5, 6])
