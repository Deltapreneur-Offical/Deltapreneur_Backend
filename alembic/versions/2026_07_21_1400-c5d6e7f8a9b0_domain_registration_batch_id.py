"""Add batch_id to domain_registration_orders for multi-domain cart checkout."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c5d6e7f8a9b0"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "domain_registration_orders",
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "idx_domain_reg_orders_batch",
        "domain_registration_orders",
        ["batch_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_domain_reg_orders_batch", table_name="domain_registration_orders")
    op.drop_column("domain_registration_orders", "batch_id")
