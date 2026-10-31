"""Keep a record of permanently deleted bookings.

Revision ID: 0018_booking_deletions
Revises: 0017_single_transfer_series
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_booking_deletions"
down_revision = "0017_single_transfer_series"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "booking_deletions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("deleted_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
    )
    op.create_index("ix_booking_deletions_booking_id", "booking_deletions", ["booking_id"])
    op.create_index("ix_booking_deletions_deleted_by_id", "booking_deletions", ["deleted_by_id"])
    op.create_index("ix_booking_deletions_deleted_at", "booking_deletions", ["deleted_at"])


def downgrade():
    op.drop_table("booking_deletions")
