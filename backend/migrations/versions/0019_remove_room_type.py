"""Remove the obsolete room classification, preserving every room and booking."""
from alembic import op
import sqlalchemy as sa

revision = "0019_remove_room_type"
down_revision = "0018_booking_deletions"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '60s'")
    op.drop_index("ix_rooms_type", table_name="rooms")
    op.drop_column("rooms", "type")


def downgrade():
    # The removed classification cannot be reconstructed. A schema rollback
    # supplies a neutral value; restore the pre-migration backup for old values.
    op.add_column("rooms", sa.Column("type", sa.String(50), nullable=False, server_default="other"))
    op.create_index("ix_rooms_type", "rooms", ["type"])
    op.alter_column("rooms", "type", server_default=None)
