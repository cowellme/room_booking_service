"""Administrator analytics for a chosen period.

A request (заявка) is the unit everywhere: a series counts once, the way the
requester submitted it. Service blocks are not requests and are left out.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from statistics import median

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..models import Booking, Room
from ..timeutils import _ZONE, local_now

OPEN_STATUSES = ("pending", "approved")
# The state a whole series is shown with: the dates that still matter win over closed ones.
STATUS_PRIORITY = ("pending", "approved", "completed", "no_show", "transferred", "rejected",
                   "cancelled_by_user", "cancelled_by_admin", "cancelled")
STATUS_LABELS = {
    "pending": "На согласовании", "approved": "Подтверждено", "completed": "Состоялось",
    "no_show": "Неявка", "rejected": "Отклонено", "cancelled": "Отменено",
    "cancelled_by_user": "Отменено пользователем", "cancelled_by_admin": "Отменено администратором",
    "transferred": "Перенесено",
}
SOURCE_LABELS = {
    "self_service": "Заявка пользователя", "phone": "Оформлено по звонку",
    "admin_direct": "Оформлено администратором", "admin_batch": "Серия администратора",
    "transfer": "Перенос", "excel_import": "Импорт из Excel",
}
MAX_PERIOD_DAYS = 366
TOP_LIMIT = 30


def _local(value: datetime | None) -> datetime | None:
    """Stored timestamps are UTC; reports speak in the institution's local time."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_ZONE).replace(tzinfo=None)


class Request:
    """All records of one submission (a single booking or a whole series)."""

    def __init__(self, records: list[Booking]):
        # The main room of a set comes first, so the request is described by it.
        records.sort(key=lambda item: (item.date, item.parent_booking_id is not None, item.time_start))
        self.records = records
        first = records[0]
        self.first = first
        statuses = {item.status for item in records}
        self.status = next((status for status in STATUS_PRIORITY if status in statuses), first.status)
        self.created = min(_local(item.created_at) or datetime.min for item in records)
        self.person = (first.customer_name or first.booked_by or "").strip() or "Не указан"
        self.department = first.department.name if first.department else "Не указано"
        self.catering = next((item.catering_required for item in records if item.catering_required is not None), None)
        self.technical_support = next((item.technical_support_required for item in records if item.technical_support_required is not None), None)
        self.equipment = sorted({value for item in records for value in (item.requested_equipment or [])})
        self.building = first.room.building.name if first.room and first.room.building else "Не указан"

    def is_open(self, now: datetime) -> bool:
        return any(item.status in OPEN_STATUSES and datetime.combine(item.date, item.time_end) > now
                   for item in self.records)

    def completed_in(self, start: date, end: date) -> bool:
        return any(item.status == "completed" and start <= item.date <= end for item in self.records)

    def created_in(self, start: date, end: date) -> bool:
        return start <= self.created.date() <= end


def _requests(db: Session, since: date | None = None) -> list[Request]:
    """Requests that can matter for a report starting at `since` (the previous period's start).

    Every figure looks at records dated, created or completed from `since` on, or at
    records still open now; older closed history is not read at all, so the report
    does not slow down as years of bookings accumulate. Without `since`: everything.
    """
    stmt = select(Booking).options(
        joinedload(Booking.room).joinedload(Room.building), joinedload(Booking.department),
    ).where(Booking.record_kind == "booking")
    if since is not None:
        since_moment = datetime.combine(since, time.min, tzinfo=_ZONE)
        stmt = stmt.where(or_(Booking.date >= since, Booking.created_at >= since_moment,
                              Booking.status.in_(OPEN_STATUSES)))
    records = list(db.scalars(stmt))
    previous = {item.id: item.previous_booking_id for item in records}

    def root(booking_id: int) -> int:
        # A transferred booking and all its replacements are one request.
        seen = set()
        while previous.get(booking_id) and booking_id not in seen:
            seen.add(booking_id)
            booking_id = previous[booking_id]
        return booking_id

    groups: dict[str, list[Booking]] = defaultdict(list)
    for item in records:
        # A series and a set of rooms (main + extra) each count as one request.
        groups[f"s:{item.series_id}" if item.series_id else f"b:{root(item.parent_booking_id or item.id)}"].append(item)
    return [Request(items) for items in groups.values()]


def _change(current: int, previous: int) -> float | None:
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def _share(counter: Counter, order: list[str] | None = None) -> list[dict]:
    keys = order or [key for key, _ in counter.most_common()]
    return [{"label": key, "value": counter.get(key, 0)} for key in keys]


def _durations(values: list[float]) -> dict:
    return {"count": len(values), "median_minutes": round(median(values)) if values else None,
            "max_minutes": round(max(values)) if values else None}


def _occupancy_heatmap(requests: list[Request], date_from: date, date_to: date) -> dict:
    """Room-hours per weekday/hour, normalized by occurrences of that weekday.

    This is not capacity utilization: simultaneous rooms add up and service
    blocks, pending and cancelled records are intentionally excluded.
    """
    start_hour, end_hour = settings.work_hours_start, settings.work_hours_end
    occurrences = [0] * 7
    for offset in range((date_to - date_from).days + 1):
        occurrences[(date_from + timedelta(days=offset)).weekday()] += 1
    minutes = [[0.0 for _ in range(start_hour, end_hour)] for _ in range(7)]
    counts = [[0 for _ in range(start_hour, end_hour)] for _ in range(7)]
    for request in requests:
        for item in request.records:
            if item.status not in ("approved", "completed") or not date_from <= item.date <= date_to:
                continue
            start = item.time_start.hour * 60 + item.time_start.minute + item.time_start.second / 60
            end = item.time_end.hour * 60 + item.time_end.minute + item.time_end.second / 60
            for column, hour in enumerate(range(start_hour, end_hour)):
                overlap = max(0.0, min(end, (hour + 1) * 60) - max(start, hour * 60))
                if overlap:
                    minutes[item.date.weekday()][column] += overlap
                    counts[item.date.weekday()][column] += 1
    return {"hours": list(range(start_hour, end_hour)), "rows": [
        {"weekday": day, "occurrences": occurrences[day], "cells": [
            {"hour": hour, "booked_minutes": round(minutes[day][column], 2),
             "booking_count": counts[day][column],
             "average_rooms": round(minutes[day][column] / (60 * occurrences[day]), 4) if occurrences[day] else None}
            for column, hour in enumerate(range(start_hour, end_hour))]}
        for day in range(7)]}


def _reason_statistics(db: Session, date_from: date, date_to: date) -> dict:
    """Count request sets once per kind and reason, by recorded action date."""
    start = datetime.combine(date_from, time.min, tzinfo=_ZONE)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=_ZONE)
    records = list(db.scalars(select(Booking).where(
        Booking.record_kind == "booking",
        or_(and_(Booking.cancelled_at >= start, Booking.cancelled_at < end),
            and_(Booking.decision_at >= start, Booking.decision_at < end)),
    )))
    parent_ids = {item.parent_booking_id for item in records if item.parent_booking_id}
    parent_series = dict(db.execute(select(Booking.id, Booking.series_id).where(Booking.id.in_(parent_ids))).all()) if parent_ids else {}
    groups = {"cancellations": defaultdict(set), "rejections": defaultdict(set)}
    labels = {"cancellations": {}, "rejections": {}}
    for item in records:
        series_id = item.series_id or parent_series.get(item.parent_booking_id)
        key = ("series", series_id) if series_id else ("booking", item.parent_booking_id or item.id)
        if item.status in ("cancelled", "cancelled_by_user", "cancelled_by_admin") and item.cancelled_at:
            kind, moment, reason = "cancellations", _local(item.cancelled_at), item.cancellation_reason
        elif item.status == "rejected" and item.decision_at:
            kind, moment, reason = "rejections", _local(item.decision_at), item.decision_reason
        else:
            continue
        if not moment or not date_from <= moment.date() <= date_to:
            continue
        label = " ".join((reason or "").split()) or "Причина не указана"
        normalized = label.casefold()
        labels[kind].setdefault(normalized, label)
        groups[kind][normalized].add(key)
    return {kind: sorted(({"label": labels[kind][reason], "value": len(ids)} for reason, ids in data.items()),
                         key=lambda row: (-row["value"], row["label"].casefold()))
            for kind, data in groups.items()}


def _room_statistics(db: Session, requests: list[Request], date_from: date, date_to: date) -> dict:
    """Hours and booking records (not request counts), including extra rooms."""
    rooms = list(db.scalars(select(Room).options(joinedload(Room.building)).where(Room.is_active)))
    values = {room.id: {"id": room.id, "number": room.number, "building_id": room.building_id,
                        "building": room.building.name, "active": room.is_active, "hours": 0.0, "bookings": 0} for room in rooms}
    for request in requests:
        for item in request.records:
            if item.status not in ("approved", "completed") or not date_from <= item.date <= date_to:
                continue
            room = item.room
            row = values.setdefault(room.id, {"id": room.id, "number": room.number, "building_id": room.building_id,
                                               "building": room.building.name, "active": room.is_active, "hours": 0.0, "bookings": 0})
            row["hours"] += (datetime.combine(item.date, item.time_end) - datetime.combine(item.date, item.time_start)).total_seconds() / 3600
            row["bookings"] += 1
    rows = list(values.values())
    buildings = {}
    for row in rows:
        building = buildings.setdefault(row["building_id"], {"id": row["building_id"], "label": row["building"], "value": 0.0})
        building["value"] += row["hours"]
    for row in buildings.values():
        row["value"] = round(row["value"], 2)
    for row in rows:
        row["hours"] = round(row["hours"], 2)
    return {"buildings": sorted(buildings.values(), key=lambda row: (-row["value"], row["label"])),
            "most": sorted(rows, key=lambda row: (-row["hours"], -row["bookings"], row["building"], row["number"])),
            "least": sorted((row for row in rows if row["active"]), key=lambda row: (row["hours"], row["bookings"], row["building"], row["number"]))}


def _cohort_requests(db: Session) -> list:
    """Read lightweight identity/status history so late extra rooms cannot look like new requests."""
    records = list(db.execute(select(Booking.id, Booking.parent_booking_id, Booking.previous_booking_id,
                                     Booking.series_id, Booking.created_at, Booking.status)
                              .where(Booking.record_kind == "booking")))
    previous = {row.id: row.previous_booking_id for row in records}
    parent_series = {row.id: row.series_id for row in records}
    def root(identifier):
        seen = set()
        while previous.get(identifier) and identifier not in seen:
            seen.add(identifier)
            identifier = previous[identifier]
        return identifier
    groups = defaultdict(list)
    for row in records:
        series_id = row.series_id or parent_series.get(row.parent_booking_id)
        key = ("series", series_id) if series_id else ("booking", root(row.parent_booking_id or row.id))
        groups[key].append(row)
    class Cohort:
        def __init__(self, items):
            self.created = min((_local(item.created_at) or datetime.min) for item in items)
            statuses = {item.status for item in items}
            self.status = next((status for status in STATUS_PRIORITY if status in statuses), items[0].status)
        def created_in(self, start, end):
            return start <= self.created.date() <= end
    return [Cohort(group) for group in groups.values()]


def _cohort_trend(requests: list[Request], date_from: date, date_to: date) -> dict:
    """Group by request creation date; outcomes are current, not historical event counts."""
    monthly = (date_to - date_from).days + 1 > 90
    buckets = {}
    day = date_from
    while day <= date_to:
        key = day.replace(day=1) if monthly else day
        buckets.setdefault(key, {"date": key.isoformat(), "new": 0, "confirmed": 0, "cancelled": 0})
        day += timedelta(days=1)
    for request in requests:
        if not request.created_in(date_from, date_to):
            continue
        day = request.created.date()
        key = day.replace(day=1) if monthly else day
        row = buckets[key]
        row["new"] += 1
        row["confirmed"] += request.status in ("approved", "completed")
        row["cancelled"] += request.status in ("cancelled", "cancelled_by_user", "cancelled_by_admin")
    return {"interval": "month" if monthly else "day", "rows": list(buckets.values())}


def build_analytics(db: Session, date_from: date, date_to: date) -> dict:
    if date_to < date_from:
        raise HTTPException(400, "Дата окончания периода раньше даты начала")
    if (date_to - date_from).days >= MAX_PERIOD_DAYS:
        raise HTTPException(400, "Период отчёта не может быть длиннее года")
    now = local_now()
    length = (date_to - date_from).days + 1
    previous_to = date_from - timedelta(days=1)
    previous_from = previous_to - timedelta(days=length - 1)
    requests = _requests(db, previous_from)
    new = [item for item in requests if item.created_in(date_from, date_to)]
    previous_new = sum(item.created_in(previous_from, previous_to) for item in requests)
    completed = sum(item.completed_in(date_from, date_to) for item in requests)
    previous_completed = sum(item.completed_in(previous_from, previous_to) for item in requests)
    current = [item for item in requests if item.is_open(now)]

    people: dict[str, dict] = defaultdict(lambda: {"current": 0, "new": 0, "completed": 0})
    for item in requests:
        row = people[item.person]
        row["current"] += item.is_open(now)
        row["new"] += item.created_in(date_from, date_to)
        row["completed"] += item.completed_in(date_from, date_to)
    responsible = sorted(({"label": name, **row} for name, row in people.items() if any(row.values())),
                         key=lambda row: (-row["current"], -row["new"], -row["completed"], row["label"]))

    stages_now = Counter("Согласование заявки" if item.status == "pending" else "Подготовка и проведение"
                         for item in current)
    moderation, preparation, total = [], [], []
    for item in new:
        decided = [entry for entry in item.records if entry.decision_at and entry.decided_by_id]
        if decided:
            decision = min(_local(entry.decision_at) for entry in decided)
            moderation.append((decision - item.created).total_seconds() / 60)
            if item.status in ("approved", "completed", "no_show"):
                start = datetime.combine(item.first.date, item.first.time_start)
                preparation.append(max(0.0, (start - decision).total_seconds() / 60))
        if item.status == "completed":
            last = item.records[-1]
            total.append((datetime.combine(last.date, last.time_end) - item.created).total_seconds() / 60)

    rooms: Counter = Counter()
    for item in requests:
        for entry in item.records:
            if entry.status in ("approved", "completed") and date_from <= entry.date <= date_to:
                minutes = (datetime.combine(entry.date, entry.time_end) - datetime.combine(entry.date, entry.time_start)).total_seconds() / 60
                rooms[f"{entry.room.number} · {entry.room.building.name}"] += minutes / 60

    daily = Counter(item.created.date() for item in new)
    days = [date_from + timedelta(days=offset) for offset in range(length)]
    equipment_items = Counter(value for item in new for value in item.equipment)
    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat(), "days": length,
                   "previous_from": previous_from.isoformat(), "previous_to": previous_to.isoformat()},
        "generated_at": now.isoformat(timespec="minutes"),
        "kpi": {
            "current": len(current),
            "new": len(new), "new_change": _change(len(new), previous_new),
            "completed": completed, "completed_change": _change(completed, previous_completed),
            "records_new": sum(len(item.records) for item in new),
        },
        "responsible": responsible,
        "departments": _share(Counter(item.department for item in new)),
        "catering": _share(Counter({True: "Да", False: "Нет", None: "Не указано"}[item.catering] for item in new),
                           ["Да", "Нет", "Не указано"]),
        "equipment": _share(Counter("Да" if item.technical_support is True else "Нет" if item.technical_support is False else "Не указано" for item in new), ["Да", "Нет", "Не указано"]),
        "equipment_items": _share(equipment_items),
        "buildings": _share(Counter(item.building for item in new)),
        "outcomes": _share(Counter(STATUS_LABELS.get(item.status, item.status) for item in new)),
        "sources": _share(Counter(SOURCE_LABELS.get(item.first.source, item.first.source) for item in new)),
        "stages_now": _share(stages_now, ["Согласование заявки", "Подготовка и проведение"]),
        "stage_times": [
            {"label": "Согласование заявки", **_durations(moderation)},
            {"label": "От решения до мероприятия", **_durations(preparation)},
            {"label": "Весь путь заявки", **_durations(total)},
        ],
        "rooms_hours": [{"label": key, "value": round(value, 1)} for key, value in rooms.most_common(15)],
        "daily_new": [{"date": day.isoformat(), "value": daily.get(day, 0)} for day in days],
        "occupancy_heatmap": _occupancy_heatmap(requests, date_from, date_to),
        "reasons": _reason_statistics(db, date_from, date_to),
        "room_statistics": _room_statistics(db, requests, date_from, date_to),
        "cohort_trend": _cohort_trend(_cohort_requests(db), date_from, date_to),
    }
