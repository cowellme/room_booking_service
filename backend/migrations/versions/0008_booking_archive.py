"""Explicit administrator archive for bookings."""
from alembic import op
import sqlalchemy as sa

revision = "0008_booking_archive"
down_revision = "0007_booking_work_center"


def upgrade():
    op.add_column("bookings", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("bookings", sa.Column("archived_by_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_bookings_archived_by", "bookings", "users", ["archived_by_id"], ["id"])
    op.create_index("ix_bookings_archived_by_id", "bookings", ["archived_by_id"])


def downgrade():
    op.drop_index("ix_bookings_archived_by_id", table_name="bookings")
    op.drop_constraint("fk_bookings_archived_by", "bookings", type_="foreignkey")
    op.drop_column("bookings", "archived_by_id")
    op.drop_column("bookings", "archived_at")
