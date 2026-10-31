"""Editable user profile and avatar."""
from alembic import op
import sqlalchemy as sa

revision = "0006_user_profile"
down_revision = "0005_catalog_details"

def upgrade():
    op.add_column("users", sa.Column("position", sa.String(200), nullable=True))
    op.add_column("users", sa.Column("phone", sa.String(50), nullable=True))
    op.add_column("users", sa.Column("department", sa.String(200), nullable=True))
    op.add_column("users", sa.Column("avatar_url", sa.String(500), nullable=True))

def downgrade():
    for column in ("avatar_url", "department", "phone", "position"):
        op.drop_column("users", column)
