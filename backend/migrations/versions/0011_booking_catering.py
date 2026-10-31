"""Whether a request needs a room for catering (for analytics and preparation).

Revision ID: 0011_booking_catering
Revises: 0010_excel_workflows
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_booking_catering"
down_revision = "0010_excel_workflows"
branch_labels = None
depends_on = None


def upgrade():
    # Nullable: existing requests stay "не указано".
    op.add_column("bookings", sa.Column("catering_required", sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column("bookings", "catering_required")
