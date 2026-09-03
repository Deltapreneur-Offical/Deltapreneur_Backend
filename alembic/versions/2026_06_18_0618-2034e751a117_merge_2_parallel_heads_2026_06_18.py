"""merge 2 parallel heads (2026-06-18)

Revision ID: 2034e751a117
Revises: v2w3x4y5z6a7, 65eccd9e4fad
Create Date: 2026-06-18 06:18:22.162824

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2034e751a117'
down_revision: Union[str, Sequence[str], None] = ('v2w3x4y5z6a7', '65eccd9e4fad')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
