"""Operational workflows migrated from the Excel booking process.

Revision ID: 0010_excel_workflows
Revises: 0009_moderation_decision
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_excel_workflows"
down_revision = "0009_moderation_decision"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=250), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_departments_code", "departments", ["code"], unique=True)
    op.create_index("ix_departments_is_active", "departments", ["is_active"])
    op.create_table(
        "department_curators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("departments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("contact", sa.String(length=200)),
    )
    op.create_index("ix_department_curators_department_id", "department_curators", ["department_id"])
    op.drop_constraint("ck_booking_status", "bookings", type_="check")
    op.create_check_constraint("ck_booking_status", "bookings", "status IN ('pending','approved','rejected','cancelled','cancelled_by_user','cancelled_by_admin','completed','no_show','transferred')")
    op.add_column("bookings", sa.Column("department_id", sa.Integer(), sa.ForeignKey("departments.id")))
    op.add_column("bookings", sa.Column("external_channel", sa.String(length=40)))
    op.add_column("bookings", sa.Column("external_reference", sa.String(length=120)))
    op.add_column("bookings", sa.Column("external_url", sa.String(length=1000)))
    op.add_column("bookings", sa.Column("series_id", sa.String(length=36)))
    op.add_column("bookings", sa.Column("previous_booking_id", sa.Integer(), sa.ForeignKey("bookings.id")))
    op.add_column("bookings", sa.Column("transfer_reason", sa.String(length=500)))
    op.add_column("bookings", sa.Column("record_kind", sa.String(length=30), nullable=False, server_default="booking"))
    op.add_column("bookings", sa.Column("hold_expires_at", sa.DateTime(timezone=True)))
    for name in ("department_id", "external_channel", "external_reference", "series_id", "previous_booking_id", "record_kind", "hold_expires_at"):
        op.create_index(f"ix_bookings_{name}", "bookings", [name])
    op.create_check_constraint("ck_booking_record_kind", "bookings", "record_kind IN ('booking','maintenance','setup','teardown','unavailable')")
    op.create_table(
        "booking_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_booking_comments_booking_id", "booking_comments", ["booking_id"])
    op.create_index("ix_booking_comments_author_id", "booking_comments", ["author_id"])
    op.create_index("ix_booking_comments_resolved_by_id", "booking_comments", ["resolved_by_id"])
    op.create_index("ix_booking_comments_created_at", "booking_comments", ["created_at"])


def downgrade():
    op.drop_table("booking_comments")
    op.drop_constraint("ck_booking_record_kind", "bookings", type_="check")
    for name in ("hold_expires_at", "record_kind", "previous_booking_id", "series_id", "external_reference", "external_channel", "department_id"):
        op.drop_index(f"ix_bookings_{name}", table_name="bookings")
    for name in ("hold_expires_at", "record_kind", "transfer_reason", "previous_booking_id", "series_id", "external_url", "external_reference", "external_channel", "department_id"):
        op.drop_column("bookings", name)
    op.drop_constraint("ck_booking_status", "bookings", type_="check")
    op.create_check_constraint("ck_booking_status", "bookings", "status IN ('pending','approved','rejected','cancelled','cancelled_by_user','cancelled_by_admin','completed','no_show')")
    op.drop_table("department_curators")
    op.drop_table("departments")
