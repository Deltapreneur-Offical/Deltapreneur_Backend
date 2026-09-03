"""ResellerClub customer and contact IDs on registration orders

Revision ID: b0c1d2e3f4rc
Revises: f7a8b9c0d1e2
Create Date: 2026-06-03 14:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b0c1d2e3f4rc"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "domain_registration_orders",
        sa.Column("resellerclub_customer_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "domain_registration_orders",
        sa.Column("resellerclub_contact_id", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("domain_registration_orders", "resellerclub_contact_id")
    op.drop_column("domain_registration_orders", "resellerclub_customer_id")
