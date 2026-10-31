from datetime import date, time, timedelta
from types import SimpleNamespace
from dataclasses import replace

from app.services import analytics
from tests.test_room_sets import env, book, extra, DAY  # noqa: F401

def test_heatmap_uses_partial_hours_actual_rooms_and_weekday_denominator(monkeypatch):
    monkeypatch.setattr(analytics, "settings", replace(analytics.settings, work_hours_start=8, work_hours_end=12))
    monday = date(2030, 1, 14)
    def record(day, start, end, status):
        return SimpleNamespace(date=day, time_start=start, time_end=end, status=status)
    records = [
        record(monday, time(8, 30), time(10), "approved"),
        record(monday, time(9), time(9, 30), "completed"),
        record(monday, time(8), time(11), "pending"),
        record(monday, time(8), time(11), "cancelled_by_admin"),
        record(monday - timedelta(days=1), time(8), time(10), "approved"),
    ]
    result = analytics._occupancy_heatmap([SimpleNamespace(records=records)], monday, monday + timedelta(days=7))
    row = result["rows"][0]
    assert result["hours"] == [8, 9, 10, 11] and row["occurrences"] == 2
    assert row["cells"][0]["booked_minutes"] == 30 and row["cells"][0]["average_rooms"] == .25
    assert row["cells"][1]["booked_minutes"] == 90 and row["cells"][1]["average_rooms"] == .75
    assert row["cells"][1]["booking_count"] == 2
    assert row["cells"][2]["booked_minutes"] == 0

def test_heatmap_integrates_complete_set_and_excludes_service_blocks(env):
    item = book(env, env.admin, extras=[extra(env, 1)], start="10:00", end="12:00")
    pending = book(env, env.anna, room=2, start="10:00", end="12:00")
    service = book(env, env.admin, room=3, start="10:00", end="12:00")
    service.record_kind = "maintenance"
    env.db.commit()
    report = analytics.build_analytics(env.db, DAY, DAY)
    row = report["occupancy_heatmap"]["rows"][DAY.weekday()]
    hour = next(cell for cell in row["cells"] if cell["hour"] == 10)
    assert item.status == "approved" and pending.status == "pending"
    assert hour["booked_minutes"] == 120 and hour["average_rooms"] == 2 and hour["booking_count"] == 2
    assert report["occupancy_heatmap"]["rows"][(DAY.weekday()+1)%7]["cells"][0]["average_rooms"] is None
