"""Sets of rooms: extra rooms booked together with a main room.

Revision ID: 0013_booking_room_sets
Revises: 0012_booking_attachments
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_booking_room_sets"
down_revision = "0012_booking_attachments"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bookings", sa.Column("parent_booking_id", sa.Integer(), sa.ForeignKey("bookings.id"), nullable=True))
    op.add_column("bookings", sa.Column("room_purpose", sa.String(200), nullable=True))
    op.create_index("ix_bookings_parent_booking_id", "bookings", ["parent_booking_id"])


def downgrade():
    op.drop_index("ix_bookings_parent_booking_id", table_name="bookings")
    op.drop_column("bookings", "room_purpose")
    op.drop_column("bookings", "parent_booking_id")
