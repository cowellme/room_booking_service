import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.chat import MessageCreate, TypingState, inbox, mark_read, people, send, set_typing, thread
from test_request_flow import env, request


def test_colleague_search_messages_and_persistent_unread(env):
    found, = people("bor", env.anna, env.db)
    assert found["target"] == f"person:{env.boris.id}" and found["title"] == "boris"
    assert found["avatar_url"] is None and isinstance(found["online"], bool)
    target = f"person:{env.boris.id}"
    send(target, MessageCreate(body="  Здравствуйте!  "), env.anna, env.db)
    assert inbox(env.anna, env.db)["unread"] == 0
    assert inbox(env.boris, env.db)["unread"] == 1
    assert inbox(env.admin, env.db)["unread"] == 0
    reverse = f"person:{env.anna.id}"
    entry, = thread(reverse, None, env.boris, env.db)["messages"]
    assert entry["body"] == "Здравствуйте!" and not entry["mine"] and not entry["read"]
    assert inbox(env.boris, env.db)["threads"][0]["last"] == {"mine": False, "read": False, "text": "Здравствуйте!"}
    mark_read(reverse, entry["id"], env.boris, env.db)
    assert inbox(env.boris, env.db)["unread"] == 0
    assert thread(target, None, env.anna, env.db)["messages"][0]["read"] is True
    assert inbox(env.anna, env.db)["threads"][0]["last"]["read"] is True
    set_typing(target, TypingState(active=True), env.anna, env.db)
    assert thread(reverse, None, env.boris, env.db)["typing"] is True
    assert inbox(env.boris, env.db)["threads"][0]["typing"] is True
    set_typing(target, TypingState(active=False), env.anna, env.db)
    assert thread(reverse, None, env.boris, env.db)["typing"] is False
    with pytest.raises(ValidationError):
        MessageCreate(body="   ")


def test_booking_chat_is_available_only_to_owner_and_admin(env):
    booking = request(env, env.anna)
    target = f"booking:{booking.id}"
    send(target, MessageCreate(body="Уточнение по заявке"), env.admin, env.db)
    assert inbox(env.anna, env.db)["threads"][0]["unread"] == 1
    for action in (
        lambda: thread(target, None, env.boris, env.db),
        lambda: send(target, MessageCreate(body="Чужое сообщение"), env.boris, env.db),
        lambda: mark_read(target, 1000, env.boris, env.db),
    ):
        with pytest.raises(HTTPException) as error:
            action()
        assert error.value.status_code == 404
    assert inbox(env.anna, env.db)["unread"] == 1
    assert thread(target, None, env.anna, env.db)["messages"][0]["body"] == "Уточнение по заявке"


def test_upload_caption_and_private_download(env):
    import base64
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db
    from app.security import csrf_protected, current_user

    actor = {"user": env.anna}
    app.dependency_overrides.update({get_db: lambda: env.db, csrf_protected: lambda: actor["user"],
                                     current_user: lambda: actor["user"]})
    data = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
    try:
        with TestClient(app) as client:
            target = f"person:{env.boris.id}"
            url = f"/api/chat/thread/{target}"
            result = client.post(url + "/file", json={"name": "акт.pdf", "body": "Проверьте",
                                                     "content": base64.b64encode(data).decode()})
            assert result.status_code == 201, result.text
            row = client.get(url).json()["messages"][0]
            assert row["body"] == "Проверьте" and row["file"]["name"] == "акт.pdf"
            assert row["file"]["preview"] == "pdf"
            assert client.get(row["file"]["url"]).content == data
            preview = client.get(row["file"]["url"] + "?inline=1")
            assert preview.headers["content-disposition"].startswith("inline")
            assert preview.headers["content-type"].startswith("application/pdf")
            actor["user"] = env.boris
            reverse = f"/api/chat/thread/person:{env.anna.id}/file/{row['id']}"
            assert client.get(reverse).headers["content-disposition"].startswith("attachment")
            actor["user"] = env.admin
            assert client.get(reverse).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_admin_owned_booking_chat_is_available_without_self_unread(env):
    booking = request(env, env.admin, room=1)
    target = f"booking:{booking.id}"
    send(target, MessageCreate(body="Заметка по собственной брони"), env.admin, env.db)
    data = thread(target, None, env.admin, env.db)
    assert data["messages"][0]["body"] == "Заметка по собственной брони"
    assert data["messages"][0]["mine"] is True
    assert inbox(env.admin, env.db)["unread"] == 0
