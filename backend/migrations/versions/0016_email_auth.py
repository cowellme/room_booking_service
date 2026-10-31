"""Email confirmation codes, password reset and per-account login protection.

Existing users are marked as confirmed so nobody loses access after the upgrade.

Revision ID: 0016_email_auth
Revises: 0015_booking_no_overlap
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_email_auth"
down_revision = "0015_booking_no_overlap"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("last_failed_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET email_verified_at = COALESCE(created_at, now())")
    op.create_table(
        "email_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requested_ip", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_email_codes_lookup", "email_codes", ["email", "purpose", "created_at"])


def downgrade():
    op.drop_index("ix_email_codes_lookup", table_name="email_codes")
    op.drop_table("email_codes")
    for column in ("locked_until", "last_failed_login_at", "failed_login_count", "session_version",
                   "password_changed_at", "email_verified_at"):
        op.drop_column("users", column)
