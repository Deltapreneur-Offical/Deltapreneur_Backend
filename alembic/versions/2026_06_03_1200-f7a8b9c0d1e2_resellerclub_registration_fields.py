"""ResellerClub registration fields and REGISTRATION_PENDING status

Revision ID: f7a8b9c0d1e2
Revises: e1f2a3b4c5d6
Create Date: 2026-06-03 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_enum e "
            "JOIN pg_type t ON e.enumtypid = t.oid "
            "WHERE t.typname = 'registration_order_status_enum' "
            "AND e.enumlabel = 'REGISTRATION_PENDING'",
        ),
    ).scalar()
    if not exists:
        op.execute(
            "ALTER TYPE registration_order_status_enum "
            "ADD VALUE 'REGISTRATION_PENDING'",
        )

    op.add_column(
        "domain_registration_orders",
        sa.Column("resellerclub_order_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "domain_registration_orders",
        sa.Column("resellerclub_action_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "domain_registration_orders",
        sa.Column("resellerclub_action_status", sa.String(64), nullable=True),
    )
    op.add_column(
        "domain_registration_orders",
        sa.Column("resellerclub_action_status_desc", sa.Text(), nullable=True),
    )
    op.add_column(
        "domain_registration_orders",
        sa.Column("resellerclub_invoice_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "domain_registration_orders",
        sa.Column("registrar_response_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "domain_registration_orders",
        sa.Column("quoted_unit_price_inr", sa.Float(), nullable=True),
    )
    op.add_column(
        "domain_registration_orders",
        sa.Column("price_source", sa.String(64), nullable=True),
    )
    op.create_index(
        "idx_domain_reg_orders_rc_order",
        "domain_registration_orders",
        ["resellerclub_order_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_domain_reg_orders_rc_order", table_name="domain_registration_orders")
    op.drop_column("domain_registration_orders", "price_source")
    op.drop_column("domain_registration_orders", "quoted_unit_price_inr")
    op.drop_column("domain_registration_orders", "registrar_response_json")
    op.drop_column("domain_registration_orders", "resellerclub_invoice_id")
    op.drop_column("domain_registration_orders", "resellerclub_action_status_desc")
    op.drop_column("domain_registration_orders", "resellerclub_action_status")
    op.drop_column("domain_registration_orders", "resellerclub_action_id")
    op.drop_column("domain_registration_orders", "resellerclub_order_id")
