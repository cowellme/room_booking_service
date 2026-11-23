"""Store event location and additional room needs without rewriting history."""
from alembic import op
import sqlalchemy as sa

revision = '0022_booking_logistics'
down_revision = '0021_review_requirements'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bookings', sa.Column('event_location', sa.String(24), nullable=True))
    for field in ('catering_storage_required', 'operations_hq_required', 'vip_room_required'):
        op.add_column('bookings', sa.Column(field, sa.Boolean(), nullable=True))


def downgrade():
    for field in ('vip_room_required', 'operations_hq_required', 'catering_storage_required', 'event_location'):
        op.drop_column('bookings', field)
