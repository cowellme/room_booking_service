"""Add registered users as read-only booking observers."""

from alembic import op
import sqlalchemy as sa

revision = "0029_booking_observers"
down_revision = "0028_booking_in_progress"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "booking_observers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assigned_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("booking_id", "user_id", name="uq_booking_observer"),
    )
    op.create_index("ix_booking_observers_booking_id", "booking_observers", ["booking_id"])
    op.create_index("ix_booking_observers_user_id", "booking_observers", ["user_id"])
    op.create_index("ix_booking_observers_assigned_by_id", "booking_observers", ["assigned_by_id"])


def downgrade():
    op.drop_table("booking_observers")
