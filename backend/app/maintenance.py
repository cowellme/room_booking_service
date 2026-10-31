"""One-off data repairs run from the command line (see cli.py)."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .database import SessionLocal
from .timeutils import _ZONE

# Columns the application filled with a naive datetime.utcnow() before the switch to
# aware UTC. Auth columns are absent: that code always wrote aware values.
NAIVE_UTC_COLUMNS = {
    "departments": ["created_at"],
    "bookings": ["created_at", "updated_at", "cancelled_at", "archived_at", "decision_at", "hold_expires_at"],
    "users": ["created_at"],
    "booking_history": ["created_at"],
    "booking_events": ["created_at"],
    "booking_attachments": ["created_at"],
    "booking_comments": ["created_at", "resolved_at"],
}
# The Excel importer stored these two as local wall-clock time, which the old
# behaviour already read correctly; they must not be shifted.
LOCAL_TIME_COLUMNS = {("bookings", "cancelled_at"), ("bookings", "decision_at")}


def fix_naive_timestamps(before: datetime, confirm: bool = False) -> dict:
    """Shift timestamps written before `before` from "UTC read as server zone" to real UTC.

    PostgreSQL reads a naive value in the session time zone. If that zone is not UTC,
    every moment the old code stored is off by the zone's offset. Nothing changes when
    the database already runs in UTC.
    """
    if before.tzinfo is None:
        before = before.replace(tzinfo=_ZONE)
    with SessionLocal() as db:
        zone_name = db.execute(text("SHOW timezone")).scalar_one()
        try:
            offset = before.astimezone(ZoneInfo(zone_name)).utcoffset() or timedelta(0)
        except Exception as exc:  # an offset-style zone such as "+03" cannot be resolved safely
            raise SystemExit(f"Unknown database time zone {zone_name!r}: {exc}")
        result = {"database_timezone": zone_name, "shift_hours": offset.total_seconds() / 3600, "rows": {}}
        if not offset:
            return result
        for table, columns in NAIVE_UTC_COLUMNS.items():
            for column in columns:
                where = f"{column} IS NOT NULL AND {column} < :before"
                if (table, column) in LOCAL_TIME_COLUMNS:
                    where += " AND source <> 'excel_import'"
                count = db.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"), {"before": before}).scalar_one()
                result["rows"][f"{table}.{column}"] = count
                if confirm and count:
                    db.execute(text(f"UPDATE {table} SET {column} = {column} + :shift WHERE {where}"),
                               {"shift": offset, "before": before})
        if confirm:
            db.commit()
    return result


