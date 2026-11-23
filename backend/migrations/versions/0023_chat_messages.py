"""Private colleague and booking conversations."""
import sqlalchemy as sa
from alembic import op

revision = "0023_chat_messages"
down_revision = "0022_booking_logistics"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sender_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("thread", sa.String(80), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_chat_sender_thread", "chat_messages", ["sender_id", "thread", "id"])
    op.create_index("ix_chat_recipient_thread", "chat_messages", ["recipient_id", "thread", "id"])


def downgrade():
    op.drop_table("chat_messages")
