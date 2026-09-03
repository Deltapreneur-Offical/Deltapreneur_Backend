"""add_tech_service_price_override_columns

Revision ID: e484eeb728a2
Revises: bidfee20 (database state — migration file not present in repo)
Create Date: 2026-08-12 15:29:59.473639

Note: The production/local DB was stamped at revision 'bidfee20' which no
longer exists as a migration file in the repository.  This migration is
therefore created as an independent branch (down_revision = None) so it
can be applied and stamped without requiring the missing parent.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e484eeb728a2'
down_revision: Union[str, Sequence[str], None] = 'c0d6f3ec6f70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'technology_services_catalogue',
        sa.Column('price_override_monthly', sa.Float(), nullable=True),
    )
    op.add_column(
        'technology_services_catalogue',
        sa.Column('price_override_annually', sa.Float(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('technology_services_catalogue', 'price_override_annually')
    op.drop_column('technology_services_catalogue', 'price_override_monthly')
