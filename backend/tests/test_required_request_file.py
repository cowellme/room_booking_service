import json
from datetime import timedelta
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app import main
from app.database import get_db
from app.models import Booking
from app.security import current_user, csrf_protected
from app.services import attachments
from test_booking_logistics import form
from test_request_flow import DAY, env


@pytest.mark.parametrize("series", [False, True])
def test_user_file_required_and_replaceable_after_approval(env, tmp_path, monkeypatch, series):
    monkeypatch.setattr(attachments, "ATTACHMENTS_DIR", tmp_path)
    actor = {"user": env.anna}
    main.app.dependency_overrides.update({get_db: lambda: env.db, current_user: lambda: actor["user"],
                                         csrf_protected: lambda: actor["user"]})
    data = form(env)
    data["date"] = DAY.isoformat()
    if series:
        data.update(room_ids=[env.rooms[0].id], date_end=(DAY + timedelta(days=1)).isoformat())
    meta = json.dumps({"booking": data, "name": "proof.txt"}).encode()
    prefix = len(meta).to_bytes(4, "big") + meta
    url = "/api/me/request-with-file" + ("?series=true" if series else "")
    try:
        with TestClient(main.app) as client:
            legacy = "/api/booking-series" if series else "/api/bookings"
            assert client.post(legacy, json=data).status_code == 422
            assert client.post(url, content=prefix).status_code == 400
            assert env.db.scalar(select(Booking.id)) is None
            sent = client.post(url, content=prefix + b"old proof")
            assert sent.status_code == 201, sent.text
            booking = env.db.get(Booking, sent.json()["id"])
            if series:
                from app.services.booking_lifecycle import transition_series_status
                transition_series_status(env.db, booking.series_id, env.admin, "approved")
            else:
                main.approve(booking.id, env.admin, env.db)
            current = client.get("/api/me/bookings").json()
            file_id = current[0]["attachments"][0]["id"]
            target = f"/api/me/attachments/{file_id}"
            headers = {"X-File-Name": "replacement.txt"}
            assert client.put(target, content=b"", headers=headers).status_code == 400
            assert client.get(f"/api/attachments/{file_id}").content == b"old proof"
            assert client.delete(f"/api/attachments/{file_id}").status_code == 403
            actor["user"] = env.boris
            assert client.put(target, content=b"other", headers=headers).status_code == 404
            actor["user"] = env.anna
            assert client.put(target, content=b"new proof", headers=headers).status_code == 200
            assert client.get(f"/api/attachments/{file_id}").content == b"new proof"
            current = client.get("/api/me/bookings").json()
            assert all(row["status"] == "approved" and row["title"] == data["title"] for row in current)
            assert all(row["file_replacements"][0]["actor"] == env.anna.full_name for row in current)
            assert all(row["file_replacements"][0]["after"] == "replacement.txt" for row in current)
    finally:
        main.app.dependency_overrides.clear()
