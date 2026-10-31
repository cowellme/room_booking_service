"""Real building and room catalog fields."""
from alembic import op
import sqlalchemy as sa

revision = "0005_catalog_details"
down_revision = "0004_booking_equipment"

def upgrade():
    op.add_column("buildings", sa.Column("image", sa.String(500), nullable=True))
    op.add_column("buildings", sa.Column("color", sa.String(7), nullable=False, server_default="#C81340"))
    op.add_column("rooms", sa.Column("floor_display", sa.String(50), nullable=True))
    op.add_column("rooms", sa.Column("area", sa.Float(), nullable=True))
    op.add_column("rooms", sa.Column("description", sa.Text(), nullable=False, server_default=""))
    op.add_column("rooms", sa.Column("usage_options", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))
    op.add_column("rooms", sa.Column("images", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))
    op.add_column("rooms", sa.Column("floor_plan", sa.String(500), nullable=True))

def downgrade():
    for column in ("floor_plan", "images", "usage_options", "description", "area", "floor_display"):
        op.drop_column("rooms", column)
    op.drop_column("buildings", "color")
    op.drop_column("buildings", "image")
