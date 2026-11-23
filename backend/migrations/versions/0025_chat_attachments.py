"""Private attachments for chat messages."""
import sqlalchemy as sa
from alembic import op

revision = "0025_chat_attachments"
down_revision = "0024_moderation_workspace"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("chat_attachments",
                    sa.Column("message_id", sa.Integer(), sa.ForeignKey("chat_messages.id", ondelete="CASCADE"), primary_key=True),
                    sa.Column("name", sa.String(200), nullable=False),
                    sa.Column("size", sa.Integer(), nullable=False),
                    sa.Column("content", sa.LargeBinary(), nullable=False))


def downgrade():
    op.drop_table("chat_attachments")
