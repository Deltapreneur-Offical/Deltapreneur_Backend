"""Add seller payout snapshot columns to domain_marketplace_transactions."""

revision = "dp_snapshot_payout_001"
down_revision = ("rp_tech_sub_retry_fields_001", "ac0c34ac14f3")
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "domain_marketplace_transactions",
        sa.Column("payout_snapshot_method", sa.String(32), nullable=True),
    )
    op.add_column(
        "domain_marketplace_transactions",
        sa.Column("payout_snapshot_upi_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "domain_marketplace_transactions",
        sa.Column("payout_snapshot_account_holder", sa.String(255), nullable=True),
    )
    op.add_column(
        "domain_marketplace_transactions",
        sa.Column("payout_snapshot_bank_name", sa.String(255), nullable=True),
    )
    op.add_column(
        "domain_marketplace_transactions",
        sa.Column("payout_snapshot_account_number", sa.String(100), nullable=True),
    )
    op.add_column(
        "domain_marketplace_transactions",
        sa.Column("payout_snapshot_ifsc", sa.String(16), nullable=True),
    )
    op.add_column(
        "domain_marketplace_transactions",
        sa.Column("payout_snapshot_account_last4", sa.String(4), nullable=True),
    )
    op.add_column(
        "domain_marketplace_transactions",
        sa.Column("payout_snapshot_captured_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "domain_marketplace_transactions",
        sa.Column("payout_snapshot_source", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("domain_marketplace_transactions", "payout_snapshot_source")
    op.drop_column("domain_marketplace_transactions", "payout_snapshot_captured_at")
    op.drop_column("domain_marketplace_transactions", "payout_snapshot_account_last4")
    op.drop_column("domain_marketplace_transactions", "payout_snapshot_ifsc")
    op.drop_column("domain_marketplace_transactions", "payout_snapshot_account_number")
    op.drop_column("domain_marketplace_transactions", "payout_snapshot_bank_name")
    op.drop_column("domain_marketplace_transactions", "payout_snapshot_account_holder")
    op.drop_column("domain_marketplace_transactions", "payout_snapshot_upi_id")
    op.drop_column("domain_marketplace_transactions", "payout_snapshot_method")
