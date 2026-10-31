"""Administrator booking work center and append-only events."""
from alembic import op
import sqlalchemy as sa

revision = "0007_booking_work_center"
down_revision = "0006_user_profile"


def upgrade():
    op.drop_constraint("ck_booking_status", "bookings", type_="check")
    op.create_check_constraint(
        "ck_booking_status", "bookings",
        "status IN ('pending','approved','rejected','cancelled','cancelled_by_user','cancelled_by_admin','completed','no_show')",
    )
    op.add_column("bookings", sa.Column("source", sa.String(30), nullable=False, server_default="self_service"))
    op.add_column("bookings", sa.Column("customer_name", sa.String(200), nullable=True))
    op.add_column("bookings", sa.Column("customer_contact", sa.String(200), nullable=True))
    op.add_column("bookings", sa.Column("participants", sa.Integer(), nullable=True))
    op.add_column("bookings", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column("bookings", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("bookings", sa.Column("cancelled_by_id", sa.Integer(), nullable=True))
    op.add_column("bookings", sa.Column("cancellation_reason", sa.String(500), nullable=True))
    op.add_column("bookings", sa.Column("cancellation_comment", sa.Text(), nullable=True))
    op.add_column("bookings", sa.Column("replacement_offered", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("bookings", sa.Column("notify_customer", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_foreign_key("fk_bookings_cancelled_by", "bookings", "users", ["cancelled_by_id"], ["id"])
    op.create_index("ix_bookings_cancelled_by_id", "bookings", ["cancelled_by_id"])
    op.create_index("ix_bookings_source", "bookings", ["source"])
    op.execute("UPDATE bookings SET customer_name = booked_by, customer_contact = email WHERE customer_name IS NULL")
    op.create_table(
        "booking_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_booking_events_booking_id", "booking_events", ["booking_id"])
    op.create_index("ix_booking_events_actor_id", "booking_events", ["actor_id"])
    op.create_index("ix_booking_events_event_type", "booking_events", ["event_type"])
    op.create_index("ix_booking_events_created_at", "booking_events", ["created_at"])
    op.execute("""
        INSERT INTO booking_events (booking_id, actor_id, event_type, summary, data, created_at)
        SELECT booking_id, actor_id, action,
               CASE action WHEN 'created' THEN 'Бронирование создано'
                           WHEN 'approved' THEN 'Бронирование подтверждено'
                           WHEN 'rejected' THEN 'Заявка отклонена'
                           WHEN 'cancelled' THEN 'Бронирование отменено'
                           ELSE 'Действие с бронированием' END,
               json_build_object('legacy_details', details), created_at
        FROM booking_history
    """)


def downgrade():
    op.drop_table("booking_events")
    op.drop_index("ix_bookings_source", "bookings")
    op.drop_index("ix_bookings_cancelled_by_id", "bookings")
    op.drop_constraint("fk_bookings_cancelled_by", "bookings", type_="foreignkey")
    for column in ("notify_customer", "replacement_offered", "cancellation_comment", "cancellation_reason",
                   "cancelled_by_id", "cancelled_at", "updated_at", "participants", "customer_contact",
                   "customer_name", "source"):
        op.drop_column("bookings", column)
    op.drop_constraint("ck_booking_status", "bookings", type_="check")
    op.create_check_constraint("ck_booking_status", "bookings", "status IN ('pending','approved','rejected','cancelled')")
