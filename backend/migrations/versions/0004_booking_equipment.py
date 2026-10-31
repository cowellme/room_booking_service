"""Requested equipment for bookings."""
from alembic import op
import sqlalchemy as sa
revision = "0004_booking_equipment"
down_revision = "0003_booking_constraints"
def upgrade():
    op.add_column("bookings", sa.Column("requested_equipment", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))
def downgrade():
    op.drop_column("bookings", "requested_equipment")
