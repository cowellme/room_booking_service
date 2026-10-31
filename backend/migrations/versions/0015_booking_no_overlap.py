"""Prevent overlapping approved occupancy for the same room in PostgreSQL.

Existing data is never repaired/deleted by this migration. Conflicts abort the
transaction; the operator must review them before retrying. No extension is
required, so deployment does not need CREATE EXTENSION privileges.
"""
from alembic import op

revision = "0015_booking_no_overlap"
down_revision = "0014_room_max_capacity"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '60s'")
    # Acquire the DDL lock before preflight: no writer can introduce a conflict
    # between the check and constraint creation. A timeout rolls back safely.
    op.execute("LOCK TABLE bookings IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$
        DECLARE conflict_count bigint;
        BEGIN
            SELECT count(*) INTO conflict_count
            FROM bookings a JOIN bookings b ON a.id < b.id
              AND a.room_id = b.room_id AND a.date = b.date
              AND a.time_start < b.time_end AND a.time_end > b.time_start
            WHERE a.status = 'approved' AND b.status = 'approved';
            IF conflict_count > 0 THEN
                RAISE EXCEPTION 'Cannot protect bookings: % overlapping approved pair(s)', conflict_count
                    USING ERRCODE = '23514',
                          HINT = 'Review conflicting bookings manually. This migration does not change booking data.';
            END IF;
        END $$
    """)
    op.execute("""
        ALTER TABLE bookings ADD CONSTRAINT ex_booking_room_time_approved
        EXCLUDE USING gist (
            int8range(room_id::bigint, room_id::bigint, '[]') WITH &&,
            tsrange(date + time_start, date + time_end, '[)') WITH &&
        ) WHERE (status = 'approved')
        DEFERRABLE INITIALLY DEFERRED
    """)


def downgrade():
    op.drop_constraint("ex_booking_room_time_approved", "bookings")
