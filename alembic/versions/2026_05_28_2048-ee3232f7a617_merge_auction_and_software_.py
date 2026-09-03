"""merge auction and software participation branches

Revision ID: ee3232f7a617
Revises: 6f7a8b9c0d1e, f5a6b7c8d9e0
Create Date: 2026-05-28 20:48:57.299159

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ee3232f7a617'
down_revision: Union[str, Sequence[str], None] = ('6f7a8b9c0d1e', 'f5a6b7c8d9e0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
