"""Remember whether each user has acknowledged the extra-room guide."""
from alembic import op
import sqlalchemy as sa

revision = "0020_extra_rooms_guide"
down_revision = "0019_remove_room_type"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("users", sa.Column("extra_rooms_guide_seen", sa.Boolean(), nullable=False, server_default=sa.false()))

def downgrade():
    op.drop_column("users", "extra_rooms_guide_seen")
