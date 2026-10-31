from datetime import date, time
from types import SimpleNamespace

from app.serializers import calendar_booking_to_dict


def test_user_calendar_payload_contains_schedule_and_operational_contact_data():
    building = SimpleNamespace(id=3, name="Первый учебный корпус", color="#C81340")
    room = SimpleNamespace(id=12, number="102", name="Лекционная аудитория", building_id=building.id, building=building)
    booking = SimpleNamespace(
        id=7,
        room_id=room.id,
        room=room,
        date=date(2026, 9, 10),
        time_start=time(10),
        time_end=time(11, 30),
        title="Программа развития руководителей",
        booking_type="lecture",
        record_kind="booking",
        status="approved",
        booked_by="Скрытое имя",
        owner=None,
        email=None,
        customer_contact="private@example.org",
        external_reference="PRIVATE-42",
        department=SimpleNamespace(code="УП-01", name="Учебные программы"),
        created_at=None,
        comment="Служебный комментарий",
    )

    result = calendar_booking_to_dict(booking)

    assert result["title"] == "Программа развития руководителей"
    assert result["time_start"] == "10:00"
    assert result["room_number"] == "102"
    assert result["building"] == "Первый учебный корпус"
    assert result["record_kind"] == "booking"
    assert result["booked_by"] == "Скрытое имя"
    assert result["customer_contact"] == "private@example.org"
    assert result["department_name"] == "Учебные программы"
    assert "comment" not in result
    assert result["external_reference"] is None
    assert calendar_booking_to_dict(booking, include_reference=True)["external_reference"] == "PRIVATE-42"
