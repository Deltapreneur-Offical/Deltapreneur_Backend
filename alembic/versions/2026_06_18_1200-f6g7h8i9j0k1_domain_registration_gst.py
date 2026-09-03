"""Add GST breakdown columns to domain registration orders.

Revision ID: f6g7h8i9j0k1
Revises: 2034e751a117
Create Date: 2026-06-18 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6g7h8i9j0k1"
down_revision: Union[str, Sequence[str], None] = "2034e751a117"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "domain_registration_orders",
        sa.Column("subtotal_inr", sa.Float(), nullable=True),
    )
    op.add_column(
        "domain_registration_orders",
        sa.Column("gst_inr", sa.Float(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE domain_registration_orders
            SET subtotal_inr = price_inr,
                gst_inr = 0
            WHERE subtotal_inr IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_column("domain_registration_orders", "gst_inr")
    op.drop_column("domain_registration_orders", "subtotal_inr")
