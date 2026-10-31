from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import analytics
from tests.test_room_sets import env, book, extra, children, DAY  # noqa: F401


def test_room_statistics_counts_extra_rooms_and_zero_usage(env):
    main = book(env, env.admin, extras=[extra(env, 1)], start="10:00", end="12:00")
    book(env, env.anna, room=2, start="10:00", end="12:00")  # pending, not counted
    env.rooms[4].is_active = False
    env.db.commit()
    result = analytics._room_statistics(env.db, analytics._requests(env.db), DAY, DAY)
    assert result["buildings"][0]["value"] == 4
    assert [(row["number"], row["hours"], row["bookings"]) for row in result["most"][:2]] == [
        ("100", 2, 1), ("101", 2, 1)]
    assert any(row["number"] == "102" and row["hours"] == 0 for row in result["least"])
    assert all(row["number"] != "104" for row in result["least"])


def test_reasons_use_action_date_deduplicate_set_and_separate_types(env):
    main = book(env, env.admin, extras=[extra(env, 1)])
    child = children(env, main)[0]
    rejection = book(env, env.anna, room=2)
    when = datetime(2030, 1, 15, 12, tzinfo=timezone.utc)
    for item in (main, child):
        item.status = "cancelled_by_admin"
        item.cancelled_at = when
        item.cancellation_reason = "Изменились планы"
    rejection.status = "rejected"
    rejection.decision_at = when
    rejection.decision_reason = "Не хватает данных"
    env.db.commit()
    result = analytics._reason_statistics(env.db, date(2030, 1, 15), date(2030, 1, 15))
    assert result["cancellations"] == [{"label": "Изменились планы", "value": 1}]
    assert result["rejections"] == [{"label": "Не хватает данных", "value": 1}]
    assert not any(analytics._reason_statistics(env.db, date(2030, 1, 16), date(2030, 1, 16)).values())


def test_trend_uses_creation_cohorts_and_current_status():
    def request(day, status):
        return SimpleNamespace(created=day, status=status, created_in=lambda start, end: start <= day.date() <= end)
    first = date(2030, 1, 14)
    requests = [request(datetime(2030, 1, 14, 10), "approved"),
                request(datetime(2030, 1, 15, 10), "cancelled_by_user"),
                request(datetime(2030, 1, 15, 11), "rejected")]
    weekly = analytics._cohort_trend(requests, first, first + timedelta(days=7))
    assert weekly["interval"] == "day"
    assert weekly["rows"][0] == {"date": "2030-01-14", "new": 1, "confirmed": 1, "cancelled": 0}
    assert weekly["rows"][1] == {"date": "2030-01-15", "new": 2, "confirmed": 0, "cancelled": 1}
    assert weekly["rows"][2]["new"] == 0
    monthly = analytics._cohort_trend(requests, first, first + timedelta(days=100))
    assert monthly["interval"] == "month" and monthly["rows"][0]["new"] == 3


def test_late_extra_does_not_turn_old_request_into_new(env):
    main = book(env, env.admin, extras=[extra(env, 1)])
    child = children(env, main)[0]
    main.created_at = datetime(2029, 1, 1, 10, tzinfo=timezone.utc)
    child.created_at = datetime(2030, 1, 14, 10, tzinfo=timezone.utc)
    main.status = "completed"
    env.db.commit()
    cohorts = analytics._cohort_requests(env.db)
    result = analytics._cohort_trend(cohorts, DAY, DAY)
    assert len(cohorts) == 1 and result["rows"][0]["new"] == 0


def test_extra_of_series_stays_in_the_same_cohort(env):
    main = book(env, env.admin, extras=[extra(env, 1)])
    child = children(env, main)[0]
    main.series_id = "series-test"
    assert child.series_id is None
    env.db.commit()
    assert len(analytics._cohort_requests(env.db)) == 1
