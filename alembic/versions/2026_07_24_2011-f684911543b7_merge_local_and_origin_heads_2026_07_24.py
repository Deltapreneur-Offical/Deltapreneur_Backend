"""merge_local_and_origin_heads_2026_07_24

Revision ID: f684911543b7
Revises: i1j2k3l4m5n6, 174ffbe7d96b
Create Date: 2026-07-24 20:11:45.479110

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f684911543b7'
down_revision: Union[str, Sequence[str], None] = ('i1j2k3l4m5n6', '174ffbe7d96b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
