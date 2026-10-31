"""Users, ownership, moderation and audit."""
from alembic import op
import sqlalchemy as sa
revision = "0002_auth_and_moderation"
down_revision = "0001_initial"

def upgrade():
    op.create_table("users",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False), sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="user"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("email"))
    op.create_index("ix_users_email", "users", ["email"]); op.create_index("ix_users_role", "users", ["role"])
    op.add_column("bookings", sa.Column("owner_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_bookings_owner", "bookings", "users", ["owner_id"], ["id"])
    op.create_index("ix_bookings_owner_id", "bookings", ["owner_id"])
    op.alter_column("bookings", "status", server_default="pending")
    op.create_table("booking_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(30), nullable=False), sa.Column("details", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_booking_history_booking_id", "booking_history", ["booking_id"])
    op.create_index("ix_booking_history_actor_id", "booking_history", ["actor_id"])

def downgrade():
    op.drop_table("booking_history"); op.drop_index("ix_bookings_owner_id", "bookings")
    op.drop_constraint("fk_bookings_owner", "bookings", type_="foreignkey"); op.drop_column("bookings", "owner_id")
    op.drop_table("users")
