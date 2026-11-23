"""Add the intermediate 'accepted for processing' booking status."""

from alembic import op


revision = "0028_booking_in_progress"
down_revision = "0027_pyrus_departments"
branch_labels = None
depends_on = None


OLD_STATUSES = "status IN ('pending','approved','rejected','cancelled','cancelled_by_user','cancelled_by_admin','completed','no_show','transferred')"
NEW_STATUSES = "status IN ('pending','in_progress','approved','rejected','cancelled','cancelled_by_user','cancelled_by_admin','completed','no_show','transferred')"


def upgrade():
    op.drop_constraint("ck_booking_status", "bookings", type_="check")
    op.create_check_constraint("ck_booking_status", "bookings", NEW_STATUSES)


def downgrade():
    # A downgrade is intentionally refused while rows use the new state.
    op.execute("UPDATE bookings SET status = 'pending' WHERE status = 'in_progress'")
    op.drop_constraint("ck_booking_status", "bookings", type_="check")
    op.create_check_constraint("ck_booking_status", "bookings", OLD_STATUSES)
