import pytest
from fastapi import HTTPException

from app.moderation_workspace import Entry, Folder, Workspace, get_workspace, history, save_workspace
from test_request_flow import env, request


def test_workspace_persists_order_tags_and_removes_folder_without_deleting_booking(env):
    booking = request(env, env.admin)
    key = f"item:{booking.id}"
    initial = Workspace(folders=[Folder(id="a", name="Важно"), Folder(id="b", name="Декабрь")],
                        version=0, entries={key: Entry(folder="b", tags=["important"], working=True)})
    assert save_workspace(initial, env.admin, env.db)["version"] == 1
    with pytest.raises(HTTPException) as err:
        save_workspace(initial, env.admin, env.db)
    assert err.value.status_code == 409
    result = save_workspace(Workspace(version=1, folders=list(reversed(initial.folders)),
                                       entries=initial.entries), env.admin, env.db)
    assert [folder["id"] for folder in result["folders"]] == ["b", "a"]
    save_workspace(Workspace(version=2, folders=[initial.folders[0]],
                             entries={key: Entry(tags=["important"])}), env.admin, env.db)
    assert get_workspace(env.admin, env.db)["entries"][key]["tags"] == ["important"]
    assert history(env.admin, env.db)[0]["id"] == booking.id


def test_workspace_rejects_assignment_to_missing_folder(env):
    with pytest.raises(HTTPException) as err:
        save_workspace(Workspace(version=0, entries={"item:1": Entry(folder="missing")}), env.admin, env.db)
    assert err.value.status_code == 422


def test_custom_tags_remain_available_after_removing_from_request(env):
    label = "Материалы у коллеги"
    saved = save_workspace(Workspace(version=0, tag_catalog=[label],
                                     entries={"item:1": Entry(tags=[label])}), env.admin, env.db)
    assert saved["entries"]["item:1"]["tags"] == [label]
    save_workspace(Workspace(version=1, tag_catalog=[label]), env.admin, env.db)
    assert get_workspace(env.admin, env.db)["tag_catalog"] == [label]


def test_workspace_persists_favorite_and_custom_tag_color(env):
    label = "Нужен контроль"
    saved = save_workspace(Workspace(
        version=0,
        tag_catalog=[label],
        tag_colors={label: "yellow"},
        entries={"item:42": Entry(tags=[label], favorite=True)},
    ), env.admin, env.db)
    assert saved["entries"]["item:42"]["favorite"] is True
    assert saved["tag_colors"][label] == "yellow"
    restored = get_workspace(env.admin, env.db)
    assert restored["entries"]["item:42"]["favorite"] is True
    assert restored["tag_colors"][label] == "yellow"


def test_workspace_persists_nested_folders_and_rejects_cycles(env):
    folders = [Folder(id="parent", name="Программы", pinned=True, collapsed=True),
               Folder(id="child", name="Ноябрь", parent_id="parent")]
    saved = save_workspace(Workspace(version=0, folders=folders,
                                     entries={"item:42": Entry(folder="child")}), env.admin, env.db)
    assert saved["folders"][1]["parent_id"] == "parent"
    assert saved["folders"][0]["pinned"] is True
    assert saved["folders"][0]["collapsed"] is True
    assert saved["entries"]["item:42"]["folder"] == "child"
    with pytest.raises(HTTPException) as error:
        save_workspace(Workspace(version=1, folders=[
            Folder(id="parent", name="Программы", parent_id="child"),
            Folder(id="child", name="Ноябрь", parent_id="parent"),
        ]), env.admin, env.db)
    assert error.value.status_code == 422


def test_booking_and_moderation_folders_are_isolated(env):
    save_workspace(Workspace(version=0, folders=[Folder(id="booking-folder", name="2026")]),
                   env.admin, env.db, "bookings")
    moderation = get_workspace(env.admin, env.db, "moderation")
    assert moderation["version"] == 1
    assert moderation["folders"] == []
    save_workspace(Workspace(version=1, folders=[Folder(id="incoming-folder", name="Срочные")]),
                   env.admin, env.db, "moderation")
    assert [item["id"] for item in get_workspace(env.admin, env.db, "bookings")["folders"]] == ["booking-folder"]
    assert [item["id"] for item in get_workspace(env.admin, env.db, "moderation")["folders"]] == ["incoming-folder"]
