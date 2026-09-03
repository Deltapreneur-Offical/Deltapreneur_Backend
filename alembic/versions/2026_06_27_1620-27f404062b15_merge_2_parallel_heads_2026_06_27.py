"""merge 2 parallel heads (2026-06-27)

Revision ID: 27f404062b15
Revises: 026e30dcf1fd, e2f3g4h5i6j6
Create Date: 2026-06-27 16:20:36.251829

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '27f404062b15'
down_revision: Union[str, Sequence[str], None] = ('026e30dcf1fd', 'e2f3g4h5i6j6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
