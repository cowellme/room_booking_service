"""Database-level backstop for room occupancy (PostgreSQL only)."""
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import ExcludeConstraint

BOOKING_OVERLAP_CONSTRAINT = "ex_booking_room_time_approved"
BOOKING_OVERLAP_MESSAGE = "Аудитория уже занята в выбранное время. Обновите данные и выберите другой интервал"


def booking_overlap_constraint():
    # A singleton integer range is equivalent to room_id equality and uses a
    # built-in GiST operator class: no server-wide extension/DBA permissions.
    # [start,end) allows consecutive bookings. All approved record kinds count,
    # including maintenance/setup/teardown/unavailable, not only normal events.
    # Defer until commit so an atomic transfer can insert its replacement before
    # marking the old record transferred, without weakening the final invariant.
    return ExcludeConstraint(
        (text("int8range(room_id::bigint, room_id::bigint, '[]')"), "&&"),
        (text("tsrange(date + time_start, date + time_end, '[)')"), "&&"),
        name=BOOKING_OVERLAP_CONSTRAINT,
        where=text("status = 'approved'"),
        deferrable=True,
        initially="DEFERRED",
    ).ddl_if(dialect="postgresql")


def database_conflict_detail(exc) -> str | None:
    """Translate only known concurrency errors, never hide unrelated DB defects."""
    code = getattr(exc.orig, "sqlstate", None)
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if code == "23P01" and constraint == BOOKING_OVERLAP_CONSTRAINT:
        return BOOKING_OVERLAP_MESSAGE
    if code in {"40P01", "40001"}:
        return "Данные изменяются другим запросом. Обновите данные и повторите действие"
    return None
