from app.main import _user_availability_view


def test_user_availability_hides_requester_identities():
    source = {
        "free": [{
            "id": 1, "building": "Второй учебный корпус",
            "conflict": None,
            "pending_requests": [{"id": 9, "customer": "Чужой пользователь", "title": "Закрытая заявка"}],
        }],
        "occupied": [{
            "id": 2, "building": "Второй учебный корпус",
            "conflict": {"booking_id": 4, "title": "Открытая программа", "time_start": "10:00", "time_end": "11:00", "customer": "Чужой заказчик"},
            "pending_requests": [],
        }],
        "alternatives": [],
        "summary": {"free": 1, "occupied": 1, "alternatives": 0},
    }

    result = _user_availability_view(source)

    assert result["free"][0]["pending_request_count"] == 1
    assert result["free"][0]["pending_requests"] == [{"status": "pending"}]
    assert "customer" not in result["occupied"][0]["conflict"]
    assert result["occupied"][0]["conflict"]["title"] == "Открытая программа"


def test_other_building_returns_only_availability_not_event_details():
    source = {"free": [], "alternatives": [], "summary": {},
              "occupied": [{"building": "Пятый учебный корпус",
                            "conflict": {"title": "Скрыто", "time_start": "10:00"},
                            "nearest_booking": {"title": "Скрыто"},
                            "pending_requests": [{"id": 1}]}]}
    item = _user_availability_view(source)["occupied"][0]
    assert item["conflict"] == {"title": "Занято"}
    assert item["nearest_booking"] is None and item["pending_requests"] == []
