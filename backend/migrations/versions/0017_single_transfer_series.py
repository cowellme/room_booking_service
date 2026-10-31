"""Transfers of a single booking no longer invent a series.

Earlier versions gave the replacement of a transferred single booking a new
series_id, so it showed up as a one-date "series" and was counted as a separate
request. A series made only of transfer replacements and without series-level
files came from that defect and is cleared; the transfer chain is still kept by
previous_booking_id.

Revision ID: 0017_single_transfer_series
Revises: 0016_email_auth
"""
from alembic import op

revision = "0017_single_transfer_series"
down_revision = "0016_email_auth"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE bookings SET series_id = NULL
        WHERE series_id IN (
            SELECT series_id FROM bookings WHERE series_id IS NOT NULL
            GROUP BY series_id HAVING bool_and(source = 'transfer')
        )
        AND series_id NOT IN (SELECT series_id FROM booking_attachments WHERE series_id IS NOT NULL)
    """)


def downgrade():
    # The generated identifiers carried no information; nothing to restore.
    pass
