"""Initial PostgreSQL schema."""
from alembic import op
import sqlalchemy as sa
revision = "0001_initial"
down_revision = None
def upgrade():
    op.create_table("buildings", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(120), nullable=False, unique=True), sa.Column("address", sa.String(255)))
    op.create_table("rooms", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("number", sa.String(30), nullable=False), sa.Column("name", sa.String(200), nullable=False), sa.Column("building_id", sa.Integer(), sa.ForeignKey("buildings.id"), nullable=False), sa.Column("floor", sa.Integer(), nullable=False), sa.Column("capacity", sa.Integer(), nullable=False), sa.Column("type", sa.String(50), nullable=False), sa.Column("equipment", sa.Text(), nullable=False), sa.Column("color", sa.String(7), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False), sa.UniqueConstraint("building_id", "number"))
    op.create_index("ix_rooms_building_id", "rooms", ["building_id"]); op.create_index("ix_rooms_type", "rooms", ["type"])
    op.create_table("bookings", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("room_id", sa.Integer(), sa.ForeignKey("rooms.id"), nullable=False), sa.Column("date", sa.Date(), nullable=False), sa.Column("time_start", sa.Time(), nullable=False), sa.Column("time_end", sa.Time(), nullable=False), sa.Column("title", sa.String(200), nullable=False), sa.Column("booking_type", sa.String(50), nullable=False), sa.Column("group_name", sa.String(100)), sa.Column("teacher", sa.String(200)), sa.Column("booked_by", sa.String(200), nullable=False), sa.Column("email", sa.String(200)), sa.Column("comment", sa.Text()), sa.Column("status", sa.String(20), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_booking_room_window", "bookings", ["room_id", "date", "time_start", "time_end"]); op.create_index("ix_bookings_date", "bookings", ["date"]); op.create_index("ix_bookings_room_id", "bookings", ["room_id"]); op.create_index("ix_bookings_status", "bookings", ["status"])
def downgrade():
    op.drop_table("bookings"); op.drop_table("rooms"); op.drop_table("buildings")
