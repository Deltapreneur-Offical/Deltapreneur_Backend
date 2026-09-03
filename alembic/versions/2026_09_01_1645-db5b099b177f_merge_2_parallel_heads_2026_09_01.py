"""merge 2 parallel heads (2026-09-01)

Revision ID: db5b099b177f
Revises: hubreg006, ops_req_rzpay_001
Create Date: 2026-09-01 16:45:25.418228

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db5b099b177f'
down_revision: Union[str, Sequence[str], None] = ('hubreg006', 'ops_req_rzpay_001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
