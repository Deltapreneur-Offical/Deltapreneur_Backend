"""merge_winner_payment_and_software_verification

Revision ID: b85582604c7b
Revises: a1b2c3d4e5f7, a7b8c9d0e1f2
Create Date: 2026-05-31 14:00:37.734953

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b85582604c7b'
down_revision: Union[str, Sequence[str], None] = ('a1b2c3d4e5f7', 'a7b8c9d0e1f2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
