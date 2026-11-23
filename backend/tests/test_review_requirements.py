import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from app.models import User
from app.schemas import BookingCreate, BatchBookingCreate
from test_request_flow import env, DAY

@pytest.mark.parametrize('schema', [BookingCreate,BatchBookingCreate])
@pytest.mark.parametrize('field', ['catering_required'])
@pytest.mark.parametrize('missing', [True,False])
def test_answers_cannot_be_missing_or_null(schema,field,missing):
    data=dict(room_id=1,room_ids=[1],date=DAY,date_end=DAY,time_start='10:00',time_end='11:00',
              title='Meeting',catering_required=False,technical_support_required=False)
    if missing:data.pop(field)
    else:data[field]=None
    with pytest.raises(ValidationError) as error:schema(**data)
    assert field in str(error.value)

def test_second_admin_blocked_by_database(env):
    env.db.add(User(email='second@test.ru',full_name='Second',role='admin',password_hash='test'))
    with pytest.raises(IntegrityError):env.db.commit()
    env.db.rollback()
