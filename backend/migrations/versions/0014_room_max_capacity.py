"""Maximum capacity of a room, shown next to the regular capacity.

Revision ID: 0014_room_max_capacity
Revises: 0013_booking_room_sets
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_room_max_capacity"
down_revision = "0013_booking_room_sets"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("rooms", sa.Column("max_capacity", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("rooms", "max_capacity")
