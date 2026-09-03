"""Add Razorpay payment id and currency to auction payments.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-24 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("payments")}

    if "razorpay_payment_id" not in cols:
        op.add_column(
            "payments",
            sa.Column("razorpay_payment_id", sa.String(length=255), nullable=True),
        )
        op.create_index(
            "ix_payments_razorpay_payment_id",
            "payments",
            ["razorpay_payment_id"],
            unique=False,
        )

    if "currency" not in cols:
        op.add_column(
            "payments",
            sa.Column(
                "currency",
                sa.String(length=8),
                nullable=False,
                server_default="INR",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("payments")}

    if "currency" in cols:
        op.drop_column("payments", "currency")

    if "razorpay_payment_id" in cols:
        op.drop_index("ix_payments_razorpay_payment_id", table_name="payments")
        op.drop_column("payments", "razorpay_payment_id")
