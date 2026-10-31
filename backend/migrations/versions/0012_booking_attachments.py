"""Files attached to a booking or to a whole series.

Revision ID: 0012_booking_attachments
Revises: 0011_booking_catering
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_booking_attachments"
down_revision = "0011_booking_catering"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "booking_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("bookings.id", ondelete="CASCADE"), nullable=True),
        sa.Column("series_id", sa.String(36), nullable=True),
        sa.Column("uploaded_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("stored_name", sa.String(100), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("booking_id IS NOT NULL OR series_id IS NOT NULL", name="ck_attachment_target"),
    )
    op.create_index("ix_booking_attachments_booking_id", "booking_attachments", ["booking_id"])
    op.create_index("ix_booking_attachments_series_id", "booking_attachments", ["series_id"])
    op.create_index("ix_booking_attachments_uploaded_by_id", "booking_attachments", ["uploaded_by_id"])


def downgrade():
    op.drop_table("booking_attachments")
