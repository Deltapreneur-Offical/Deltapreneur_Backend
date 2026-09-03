"""software auction winner payment columns

Revision ID: b4c5d6e7f8a9
Revises: ac0c34ac14f3
Create Date: 2026-07-20 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "ac0c34ac14f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "software_auctions",
        sa.Column("winner_payment_order_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "software_auctions",
        sa.Column("winner_payment_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "software_auctions",
        sa.Column(
            "winner_payment_paid",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("software_auctions", "winner_payment_paid")
    op.drop_column("software_auctions", "winner_payment_id")
    op.drop_column("software_auctions", "winner_payment_order_id")
