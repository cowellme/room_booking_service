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


def test_phone_booking_requires_department_at_submission():
    from fastapi import HTTPException
    from app.main import require_request_details

    payload = PhoneBookingCreate(catering_required=False, event_location="moscow_campus",
        catering_storage_required=False, operations_hq_required=False, vip_room_required=False,
        room_id=1, date=date(2020, 1, 1), time_start=time(10), time_end=time(11),
        title="Встреча", customer_name="Учебное управление", participants=8, external_reference="42")
    with pytest.raises(HTTPException) as error:
        require_request_details(payload, None)
    assert "подразделение" in error.value.detail
    payload.department_name = "ИГСУ"
    require_request_details(payload, None)


def test_cancellation_requires_a_reason():
    with pytest.raises(ValidationError):
        BookingCancelRequest(reason="", comment="Пояснение")


def test_cancellation_requires_a_comment():
    with pytest.raises(ValidationError):
        BookingCancelRequest(reason="Отмена заказчиком", comment="")


def test_equipment_is_reduced_to_clean_categories():
    result = _equipment_categories("Компьютеры: 24 шт, Видеостена — 1 шт, Колонки мобильные: 2 шт")
    assert result == {"компьютер", "видеостена", "колонки"}
