"""merge 2 parallel heads (2026-06-20)

Revision ID: 48c93a49de42
Revises: f2g3h4i5j6k7, f6g7h8i9j0k1
Create Date: 2026-06-20 15:19:19.832990

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '48c93a49de42'
down_revision: Union[str, Sequence[str], None] = ('f2g3h4i5j6k7', 'f6g7h8i9j0k1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
