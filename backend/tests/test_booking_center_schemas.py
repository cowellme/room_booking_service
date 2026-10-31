from datetime import date, timedelta, time
import pytest
from pydantic import ValidationError
from app.schemas import AvailabilityRequest, BookingCancelRequest, PhoneBookingCreate
from app.main import _equipment_categories


def test_availability_rejects_reversed_time():
    with pytest.raises(ValidationError):
        AvailabilityRequest(date=date.today() + timedelta(days=1), time_start=time(12), time_end=time(11))


def test_phone_booking_accepts_catalog_equipment():
    payload = PhoneBookingCreate(catering_required=False, technical_support_required=False, 
        room_id=1, date=date.today() + timedelta(days=1), time_start=time(10), time_end=time(11),
        title="Совещание", customer_name="Управление проектов", customer_contact="+7 900 000-00-00",
        participants=15, department_id=1, requested_equipment=["Проектор", "Видеостена"],
    )
    assert payload.requested_equipment == ["Проектор", "Видеостена"]


def test_phone_booking_requires_contact_and_department():
    with pytest.raises(ValidationError):
        PhoneBookingCreate(catering_required=False, technical_support_required=False, 
            room_id=1, date=date.today() + timedelta(days=1), time_start=time(10), time_end=time(11),
            title="Встреча", customer_name="Учебное управление", participants=8,
        )


def test_cancellation_requires_a_reason():
    with pytest.raises(ValidationError):
        BookingCancelRequest(reason="", comment="Пояснение")


def test_cancellation_requires_a_comment():
    with pytest.raises(ValidationError):
        BookingCancelRequest(reason="Отмена заказчиком", comment="")


def test_equipment_is_reduced_to_clean_categories():
    result = _equipment_categories("Компьютеры: 24 шт, Видеостена — 1 шт, Колонки мобильные: 2 шт")
    assert result == {"компьютер", "видеостена", "колонки"}
