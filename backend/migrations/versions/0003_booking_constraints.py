"""Booking integrity constraints."""
from alembic import op
revision = "0003_booking_constraints"
down_revision = "0002_auth_and_moderation"
def upgrade():
    op.create_check_constraint("ck_booking_time_order", "bookings", "time_end > time_start")
    op.create_check_constraint("ck_booking_status", "bookings", "status IN ('pending','approved','rejected','cancelled')")
def downgrade():
    op.drop_constraint("ck_booking_status", "bookings", type_="check")
    op.drop_constraint("ck_booking_time_order", "bookings", type_="check")
