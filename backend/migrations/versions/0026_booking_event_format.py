"""Add a normalized event format to bookings.

Revision ID: 0026_booking_event_format
Revises: 0025_chat_attachments
"""
from alembic import op
import sqlalchemy as sa


revision = "0026_booking_event_format"
down_revision = "0025_chat_attachments"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "bookings",
        sa.Column("event_format", sa.String(length=120), nullable=False, server_default="Другое"),
    )
    op.alter_column("bookings", "event_format", server_default=None)


def downgrade():
    op.drop_column("bookings", "event_format")
