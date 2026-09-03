"""merge heads

Revision ID: 5ac99fa5f19e
Revises: 673e28543ac5, b143890b6a7e
Create Date: 2026-05-21 16:33:09.828505

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5ac99fa5f19e'
down_revision: Union[str, Sequence[str], None] = ('673e28543ac5', 'b143890b6a7e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
