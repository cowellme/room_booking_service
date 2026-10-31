from app.main import _user_availability_view


def test_user_availability_hides_requester_identities():
    source = {
        "free": [{
            "id": 1,
            "conflict": None,
            "pending_requests": [{"id": 9, "customer": "Чужой пользователь", "title": "Закрытая заявка"}],
        }],
        "occupied": [{
            "id": 2,
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
