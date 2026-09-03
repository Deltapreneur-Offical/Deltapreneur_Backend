"""Add map_url to franchise_applications. Revision ID: hubreg005
"""
from alembic import op
import sqlalchemy as sa

revision = "hubreg005"
down_revision = "hubreg004"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("franchise_applications", sa.Column("map_url", sa.String(500), nullable=True))

def downgrade() -> None:
    op.drop_column("franchise_applications", "map_url")
