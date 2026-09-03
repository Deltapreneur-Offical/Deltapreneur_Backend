"""merge 2 parallel heads (2026-06-27)

Revision ID: da1616ed8692
Revises: b3c4d5e6f7a9, f3g4h5i6j7k7
Create Date: 2026-06-27 17:20:06.832174

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'da1616ed8692'
down_revision: Union[str, Sequence[str], None] = ('b3c4d5e6f7a9', 'f3g4h5i6j7k7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
