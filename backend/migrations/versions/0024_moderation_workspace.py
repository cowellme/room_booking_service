"""Store personal moderation folders and tags."""
import sqlalchemy as sa
from alembic import op

revision = "0024_moderation_workspace"
down_revision = "0023_chat_messages"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("moderation_workspaces",
                    sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
                    sa.Column("version", sa.Integer(), nullable=False),
                    sa.Column("data", sa.JSON(), nullable=False))


def downgrade():
    op.drop_table("moderation_workspaces")
