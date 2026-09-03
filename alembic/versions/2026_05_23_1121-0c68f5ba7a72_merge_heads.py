"""merge_heads

Revision ID: 0c68f5ba7a72
Revises: f9e8d7c6b5a4, 5ac99fa5f19e
Create Date: 2026-05-23 11:21:26.441027

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0c68f5ba7a72'
down_revision: Union[str, Sequence[str], None] = ('f9e8d7c6b5a4', '5ac99fa5f19e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
