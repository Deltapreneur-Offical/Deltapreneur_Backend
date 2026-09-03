"""merge 2 parallel heads (2026-07-22)

Revision ID: 1497a64dde10
Revises: va_20260718_1700, c5d6e7f8a9b0
Create Date: 2026-07-22 13:33:10.923686

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1497a64dde10'
down_revision: Union[str, Sequence[str], None] = ('va_20260718_1700', 'c5d6e7f8a9b0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
