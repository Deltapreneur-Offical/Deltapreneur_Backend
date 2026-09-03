"""community auction winner payment columns

Revision ID: a1b2c3d4e5f7
Revises: ee3232f7a617
Create Date: 2026-05-30 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, Sequence[str], None] = "ee3232f7a617"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "community_auctions",
        sa.Column("winner_payment_order_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "community_auctions",
        sa.Column("winner_payment_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "community_auctions",
        sa.Column(
            "winner_payment_paid",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("community_auctions", "winner_payment_paid")
    op.drop_column("community_auctions", "winner_payment_id")
    op.drop_column("community_auctions", "winner_payment_order_id")
