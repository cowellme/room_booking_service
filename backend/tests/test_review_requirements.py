from datetime import date, datetime, time, timedelta, timezone
import pytest
from pydantic import ValidationError
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.models import Booking, BookingEvent, User
from app.schemas import BookingCreate, BatchBookingCreate
from app.services import booking_lifecycle as lifecycle
from app.services.work_calendar import add_working_days, is_working_day, review_info
from test_request_flow import env, request, series, DAY

@pytest.mark.parametrize('day,expected', [
    (date(2026,1,9),False),(date(2026,3,9),False),(date(2026,5,11),False),
    (date(2026,11,4),False),(date(2026,12,31),False),
    (date(2027,2,20),True),(date(2027,2,22),False),(date(2027,5,3),False),
    (date(2027,5,10),False),(date(2027,6,14),False),(date(2027,11,5),False),
])
def test_official_calendar(day,expected):
    assert is_working_day(day) is expected

def test_new_year_boundary():
    assert add_working_days(date(2026,12,30)) == date(2027,1,19)

def test_review_deadline_institution_timezone():
    created = datetime(2026,11,2,9,tzinfo=timezone.utc)
    info = review_info(created,datetime(2026,11,12,11,59))
    assert info['review_deadline'] == '2026-11-12T12:00:00+03:00'
    assert info['review_days_left'] == 1
    assert not info['review_overdue']
    assert review_info(created,datetime(2026,11,12,12))['review_overdue']

@pytest.mark.parametrize('schema', [BookingCreate,BatchBookingCreate])
@pytest.mark.parametrize('field', ['catering_required','technical_support_required'])
@pytest.mark.parametrize('missing', [True,False])
def test_answers_cannot_be_missing_or_null(schema,field,missing):
    data=dict(room_id=1,room_ids=[1],date=DAY,date_end=DAY,time_start='10:00',time_end='11:00',
              title='Meeting',catering_required=False,technical_support_required=False)
    if missing:data.pop(field)
    else:data[field]=None
    with pytest.raises(ValidationError) as error:schema(**data)
    assert field in str(error.value)

def test_pending_expires_to_archive_not_completed(env):
    item=request(env,env.anna)
    item.created_at=datetime(2026,11,2,9,tzinfo=timezone.utc)
    env.db.commit()
    env.clock.now=datetime(2026,11,12,11,59)
    assert lifecycle.expire_pending_requests(env.db)==0
    env.clock.now=datetime(2026,11,12,12)
    assert lifecycle.expire_pending_requests(env.db)==1
    assert item.status=='rejected' and item.archived_at is not None
    assert 'истёк срок' in item.decision_reason
    assert lifecycle.expire_pending_requests(env.db)==0
    assert env.db.scalar(select(func.count()).select_from(BookingEvent).where(BookingEvent.booking_id==item.id,BookingEvent.event_type=='expired'))==1

def test_series_expires_together(env):
    items=series(env,env.anna)
    for item in items:item.created_at=datetime(2026,11,2,9,tzinfo=timezone.utc)
    env.db.commit();env.clock.now=datetime(2026,11,12,12)
    assert lifecycle.expire_pending_requests(env.db)==len(items)
    assert all(item.archived_at and item.status=='rejected' for item in items)

def test_second_admin_blocked_by_database(env):
    env.db.add(User(email='second@test.ru',full_name='Second',role='admin',password_hash='test'))
    with pytest.raises(IntegrityError):env.db.commit()
    env.db.rollback()
