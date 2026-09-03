"""Add purchase_addon_services to software_purchases.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-06-01 18:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "software_purchases",
        sa.Column("purchase_addon_services", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("software_purchases", "purchase_addon_services")
