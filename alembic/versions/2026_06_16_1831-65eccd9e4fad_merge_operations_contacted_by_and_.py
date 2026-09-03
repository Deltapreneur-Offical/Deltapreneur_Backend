"""merge operations contacted_by and venture cleanup heads

Revision ID: 65eccd9e4fad
Revises: c1d2e3f4g5h6, e6f7a8b9c0d1
Create Date: 2026-06-16 18:31:21.429765

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "65eccd9e4fad"
down_revision: Union[str, Sequence[str], None] = (
    "c1d2e3f4g5h6",
    "e6f7a8b9c0d1",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
