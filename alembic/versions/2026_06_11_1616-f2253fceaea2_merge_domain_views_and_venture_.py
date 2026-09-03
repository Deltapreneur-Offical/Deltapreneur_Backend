"""merge domain views and venture governance heads

Revision ID: f2253fceaea2
Revises: d7e8f9a0b1c2, m1n2o3p4q5r6
Create Date: 2026-06-11 16:16:14.219657

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2253fceaea2'
down_revision: Union[str, Sequence[str], None] = ('d7e8f9a0b1c2', 'm1n2o3p4q5r6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
