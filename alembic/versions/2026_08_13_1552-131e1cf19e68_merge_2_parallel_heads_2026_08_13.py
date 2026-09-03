"""merge 2 parallel heads (2026-08-13)

Revision ID: 131e1cf19e68
Revises: taxinv001, rp_tech_sub_email_sent_001
Create Date: 2026-08-13 15:52:52.961700

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '131e1cf19e68'
down_revision: Union[str, Sequence[str], None] = ('taxinv001', 'rp_tech_sub_email_sent_001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
