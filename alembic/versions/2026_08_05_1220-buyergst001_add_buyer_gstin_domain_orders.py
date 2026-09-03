"""Add buyer_gstin to domain_registration_orders.

Revision ID: buyergst001
Revises: trackrec001
Create Date: 2026-08-05 12:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "buyergst001"
down_revision: Union[str, Sequence[str], None] = "trackrec001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "domain_registration_orders",
        sa.Column("buyer_gstin", sa.String(length=15), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("domain_registration_orders", "buyer_gstin")
