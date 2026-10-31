"""Files attached to bookings and series: upload, access rules, listing, transfer and cleanup."""
from datetime import date, time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import get_db
from app.models import Base, Booking, Building, Room, User
from app.schemas import BookingTransferRequest
from app.security import csrf_protected, current_user
from app.services import attachments, operations


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(attachments, "ATTACHMENTS_DIR", tmp_path)
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    event.listen(engine, "connect", lambda conn, _: conn.create_function("pg_advisory_xact_lock", 1, lambda key: None))
    Base.metadata.create_all(engine)
    db = sessionmaker(engine, expire_on_commit=False)()
    building = Building(name="Корпус 1"); db.add(building); db.flush()
    room = Room(number="101", name="Ауд", building_id=building.id, capacity=30)
    users = {n: User(email=f"{n}@t.ru", full_name=n, password_hash="x", role="admin" if n == "admin" else "user")
             for n in ("admin", "anna", "boris")}
    db.add_all([room, *users.values()]); db.flush()
    def booking(owner, series_id=None, day=14, status="pending"):
        item = Booking(room_id=room.id, owner_id=owner.id, date=date(2030, 1, day), time_start=time(10), time_end=time(12),
                       title="Семинар", booked_by=owner.full_name, series_id=series_id, status=status)
        db.add(item); db.commit(); return item
    yield type("Env", (), {"db": db, "room": room, "booking": staticmethod(booking), "dir": tmp_path, **users})
    db.close()


def test_owner_uploads_and_admin_sees_file(env):
    item = env.booking(env.anna)
    data = attachments.save_attachment(env.db, env.anna, b"%PDF-1.4", "%D0%9F%D1%80%D0%BE%D0%B3%D1%80%D0%B0%D0%BC%D0%BC%D0%B0.pdf", booking_id=item.id)
    assert data["name"] == "Программа.pdf" and data["viewable"] and data["size"] == 8
    assert attachments.attachments_for(env.db, [item])[item.id][0]["id"] == data["id"]
    _, path = attachments.get_attachment_for(env.db, env.admin, data["id"])
    assert path.read_bytes() == b"%PDF-1.4"


def test_stranger_cannot_upload_or_open(env):
    item = env.booking(env.anna)
    with pytest.raises(HTTPException) as error:
        attachments.save_attachment(env.db, env.boris, b"%PDF-x", "a.pdf", booking_id=item.id)
    assert error.value.status_code == 404
    data = attachments.save_attachment(env.db, env.anna, b"%PDF-x", "a.pdf", booking_id=item.id)
    with pytest.raises(HTTPException):
        attachments.get_attachment_for(env.db, env.boris, data["id"])


@pytest.mark.parametrize("name,size,code", [("virus.exe", 3, 415), ("page.html", 3, 415), ("empty.pdf", 0, 400),
                                            ("big.pdf", attachments.MAX_FILE_BYTES + 1, 413)])
def test_rejected_files(env, name, size, code):
    item = env.booking(env.anna)
    with pytest.raises(HTTPException) as error:
        attachments.save_attachment(env.db, env.anna, b"x" * size, name, booking_id=item.id)
    assert error.value.status_code == code
    assert not list(env.dir.iterdir())


def test_series_file_is_shown_on_every_date(env):
    items = [env.booking(env.anna, series_id="s-1", day=d) for d in (14, 15, 16)]
    attachments.save_attachment(env.db, env.anna, b"PK\x03\x04x", "list.xlsx", series_id="s-1")
    files = attachments.attachments_for(env.db, items)
    assert all(len(files[i.id]) == 1 and files[i.id][0]["scope"] == "series" for i in items)
    with pytest.raises(HTTPException):
        attachments.save_attachment(env.db, env.boris, b"PK\x03\x04x", "list.xlsx", series_id="s-1")


def test_user_cannot_add_to_closed_request_but_admin_can(env):
    item = env.booking(env.anna, status="rejected")
    with pytest.raises(HTTPException) as error:
        attachments.save_attachment(env.db, env.anna, b"%PDF-x", "a.pdf", booking_id=item.id)
    assert error.value.status_code == 409
    attachments.save_attachment(env.db, env.admin, b"%PDF-x", "a.pdf", booking_id=item.id)


def test_limit_of_files(env):
    item = env.booking(env.anna)
    for i in range(attachments.MAX_FILES_PER_TARGET):
        attachments.save_attachment(env.db, env.anna, b"x", f"{i}.txt", booking_id=item.id)
    with pytest.raises(HTTPException) as error:
        attachments.save_attachment(env.db, env.anna, b"x", "more.txt", booking_id=item.id)
    assert error.value.status_code == 409


def test_delete_rules_and_file_cleanup(env):
    item = env.booking(env.anna)
    data = attachments.save_attachment(env.db, env.admin, b"%PDF-x", "a.pdf", booking_id=item.id)
    with pytest.raises(HTTPException) as error:
        attachments.delete_attachment(env.db, env.anna, data["id"])
    assert error.value.status_code == 403
    attachments.delete_attachment(env.db, env.admin, data["id"])
    assert not list(env.dir.iterdir())


def test_transfer_keeps_files(env, monkeypatch):
    item = env.booking(env.anna, status="approved")
    attachments.save_attachment(env.db, env.anna, b"%PDF-x", "a.pdf", booking_id=item.id)
    monkeypatch.setattr(operations, "validate_booking_window", lambda *a: None)
    moved = operations.transfer_booking(env.db, item, BookingTransferRequest(catering_required=False, technical_support_required=False, 
        room_id=env.room.id, date=date(2030, 1, 20), time_start="10:00", time_end="12:00", title="Семинар",
        reason="Перенос по просьбе"), env.admin)
    assert [f["name"] for f in attachments.attachments_for(env.db, [moved])[moved.id]] == ["a.pdf"]


def test_endpoints_upload_open_and_download(env):
    item = env.booking(env.anna)
    who = {"user": env.anna}
    main.app.dependency_overrides[get_db] = lambda: env.db
    main.app.dependency_overrides[current_user] = lambda: who["user"]
    main.app.dependency_overrides[csrf_protected] = lambda: who["user"]
    try:
        client = TestClient(main.app)
        response = client.post(f"/api/bookings/{item.id}/attachments", content=PNG,
                               headers={"X-File-Name": "%D1%81%D1%85%D0%B5%D0%BC%D0%B0.png"})
        assert response.status_code == 201, response.text
        file_id = response.json()["id"]
        opened = client.get(f"/api/attachments/{file_id}")
        assert opened.status_code == 200 and opened.content == PNG
        assert opened.headers["content-type"] == "image/png"
        assert opened.headers["content-disposition"].startswith("inline")
        downloaded = client.get(f"/api/attachments/{file_id}?download=1")
        assert downloaded.headers["content-disposition"].startswith("attachment")
        mine = client.get("/api/me/bookings").json()
        assert mine[0]["attachments"][0]["name"] == "схема.png"
        who["user"] = env.boris
        assert client.get(f"/api/attachments/{file_id}").status_code == 404
    finally:
        main.app.dependency_overrides.clear()


PNG = b"\x89PNG\r\n\x1a\n" + b"x"


@pytest.mark.parametrize("content,name", [(b"MZ\x90\x00", "report.pdf"), (b"%PDF-1.4", "table.xlsx"),
                                          (b"MZ\x90\x00binary", "notes.txt"), (b"RIFF0000AVI ", "photo.webp")])
def test_content_must_match_the_extension(env, content, name):
    item = env.booking(env.anna)
    with pytest.raises(HTTPException) as error:
        attachments.save_attachment(env.db, env.anna, content, name, booking_id=item.id)
    assert error.value.status_code == 415
