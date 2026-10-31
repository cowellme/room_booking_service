"""Explicit technical-support choice and a single administrator account."""
from alembic import op
import sqlalchemy as sa

revision = '0021_review_requirements'
down_revision = '0020_extra_rooms_guide'
branch_labels = None
depends_on = None

def upgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM users WHERE role = 'admin'")) > 1:
        raise RuntimeError('Several administrators exist. Choose the designated administrator before migration; no accounts were changed.')
    # NULL preserves the historical fact that old requests did not answer this question.
    op.add_column('bookings', sa.Column('technical_support_required', sa.Boolean(), nullable=True))
    op.create_index('uq_users_single_admin', 'users', ['role'], unique=True,
                    postgresql_where=sa.text("role = 'admin'"), sqlite_where=sa.text("role = 'admin'"))

def downgrade():
    op.drop_index('uq_users_single_admin', table_name='users')
    op.drop_column('bookings', 'technical_support_required')
