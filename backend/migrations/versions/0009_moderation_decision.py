"""Persist moderation decisions visible to booking owners."""
from alembic import op
import sqlalchemy as sa

revision = "0009_moderation_decision"
down_revision = "0008_booking_archive"


def upgrade():
    op.add_column("bookings", sa.Column("decision_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("bookings", sa.Column("decided_by_id", sa.Integer(), nullable=True))
    op.add_column("bookings", sa.Column("decision_reason", sa.String(500), nullable=True))
    op.create_foreign_key("fk_bookings_decided_by", "bookings", "users", ["decided_by_id"], ["id"])
    op.create_index("ix_bookings_decided_by_id", "bookings", ["decided_by_id"])


def downgrade():
    op.drop_index("ix_bookings_decided_by_id", table_name="bookings")
    op.drop_constraint("fk_bookings_decided_by", "bookings", type_="foreignkey")
    op.drop_column("bookings", "decision_reason")
    op.drop_column("bookings", "decided_by_id")
    op.drop_column("bookings", "decision_at")
