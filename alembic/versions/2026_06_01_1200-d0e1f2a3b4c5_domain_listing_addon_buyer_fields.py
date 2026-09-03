"""Domain listing addon services and buyer contact fields.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-06-01 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "domain_listings",
        sa.Column("purchase_addon_services", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "domain_listings",
        sa.Column("purchase_buyer_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "domain_listings",
        sa.Column("purchase_buyer_email", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "domain_listings",
        sa.Column("purchase_buyer_phone", sa.String(length=32), nullable=True),
    )
    op.execute(
        sa.text(
            """
            DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_enum e
                JOIN pg_type t ON e.enumtypid = t.oid
                WHERE t.typname = 'marketplace_payment_status_enum'
                  AND e.enumlabel = 'CONTACT_PENDING'
              ) THEN
                ALTER TYPE marketplace_payment_status_enum ADD VALUE 'CONTACT_PENDING';
              END IF;
            END $$;
            """
        )
    )


def downgrade() -> None:
    op.drop_column("domain_listings", "purchase_buyer_phone")
    op.drop_column("domain_listings", "purchase_buyer_email")
    op.drop_column("domain_listings", "purchase_buyer_name")
    op.drop_column("domain_listings", "purchase_addon_services")
