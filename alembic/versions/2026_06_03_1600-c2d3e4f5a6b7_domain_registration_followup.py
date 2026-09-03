"""Domain registration follow-up: email flags and registrar sync timestamp."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c2d3e4f5a6b7"
down_revision = "b0c1d2e3f4rc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "domain_registration_orders",
        sa.Column("last_registrar_sync_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "domain_registration_orders",
        sa.Column("email_receipt_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "domain_registration_orders",
        sa.Column("email_submitted_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "domain_registration_orders",
        sa.Column("email_active_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "domain_registration_orders",
        sa.Column("email_raa_pending_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "domain_registration_orders",
        sa.Column("email_failed_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("domain_registration_orders", "email_failed_sent")
    op.drop_column("domain_registration_orders", "email_raa_pending_sent")
    op.drop_column("domain_registration_orders", "email_active_sent")
    op.drop_column("domain_registration_orders", "email_submitted_sent")
    op.drop_column("domain_registration_orders", "email_receipt_sent")
    op.drop_column("domain_registration_orders", "last_registrar_sync_at")
