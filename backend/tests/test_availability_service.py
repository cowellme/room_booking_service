from datetime import date, time
from types import SimpleNamespace

from app.schemas import AvailabilityRequest
from app.services.availability import build_availability, equipment_categories


class FakeSession:
    def __init__(self, rooms, bookings):
        self.results = [rooms, bookings]
        self.calls = 0

    def scalars(self, _statement):
        result = self.results[self.calls]
        self.calls += 1
        return result


def room(room_id, number, building):
    return SimpleNamespace(
        id=room_id, number=number, name=f"Аудитория {number}", building_id=building.id,
        building=building, floor=1, floor_display="1 этаж", capacity=30, area=40.0,
        equipment="Проектор, компьютер", description="",
        usage_options=[], images=[], floor_plan=None, is_active=True,
    )


def test_availability_uses_two_batched_queries_and_groups_results():
    building = SimpleNamespace(id=1, name="Первый корпус", image=None, color="#C81340")
    free_room, occupied_room = room(1, "101", building), room(2, "102", building)
    conflict = SimpleNamespace(
        id=5, room_id=2, status="approved", time_start=time(10), time_end=time(11),
        created_at=None, title="Занятие", customer_name="Заказчик", booked_by="Менеджер",
    )
    db = FakeSession([free_room, occupied_room], [conflict])
    payload = AvailabilityRequest(
        date=date.today(), time_start=time(10, 30), time_end=time(11, 30),
        participants=20, equipment=["Проектор"],
    )

    result = build_availability(db, payload)

    assert db.calls == 2
    assert [item["id"] for item in result["free"]] == [1]
    assert [item["id"] for item in result["occupied"]] == [2]
    assert result["summary"] == {"free": 1, "occupied": 1, "alternatives": 0}


def test_equipment_categories_are_normalized_consistently():
    result = equipment_categories("LED-видеостена, 24 компьютера, световое оборудование, контент-камера")
    assert result == {"видеостена", "компьютер", "световое оборудование", "контент-камера"}
