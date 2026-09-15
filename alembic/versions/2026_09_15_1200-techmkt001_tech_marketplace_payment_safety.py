"""Technology marketplace payment, delivery snapshot, and payout safety.

Revision ID: techmkt001
Revises: perf_listing_indexes_001
Create Date: 2026-09-15 12:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "techmkt001"
down_revision: Union[str, Sequence[str], None] = "perf_listing_indexes_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE software_payment_status_enum ADD VALUE IF NOT EXISTS 'CANCELLED'"
    )
    op.execute(
        "ALTER TYPE software_payment_status_enum ADD VALUE IF NOT EXISTS 'REFUNDED'"
    )
    op.add_column(
        "software_listings",
        sa.Column("rejected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "software_purchases",
        sa.Column("razorpay_refund_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "software_purchases",
        sa.Column("refund_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "software_purchases",
        sa.Column("delivered_github_link", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "software_purchases",
        sa.Column("delivered_documentation_urls", sa.Text(), nullable=True),
    )
    op.add_column(
        "software_purchases",
        sa.Column("delivered_download_urls", sa.Text(), nullable=True),
    )
    op.add_column(
        "software_purchases",
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_software_purchases_rzp_order_software
        ON software_purchases (razorpay_order_id, software_id)
        WHERE razorpay_order_id IS NOT NULL AND btrim(razorpay_order_id) <> ''
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_software_purchases_rzp_payment_software
        ON software_purchases (razorpay_payment_id, software_id)
        WHERE razorpay_payment_id IS NOT NULL AND btrim(razorpay_payment_id) <> ''
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_seller_payouts_software_purchase_id
        ON seller_payouts (software_purchase_id)
        WHERE software_purchase_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_seller_payouts_software_purchase_id")
    op.execute("DROP INDEX IF EXISTS uq_software_purchases_rzp_payment_software")
    op.execute("DROP INDEX IF EXISTS uq_software_purchases_rzp_order_software")
    op.drop_column("software_purchases", "delivered_at")
    op.drop_column("software_purchases", "delivered_download_urls")
    op.drop_column("software_purchases", "delivered_documentation_urls")
    op.drop_column("software_purchases", "delivered_github_link")
    op.drop_column("software_purchases", "refund_completed_at")
    op.drop_column("software_purchases", "razorpay_refund_id")
    op.drop_column("software_listings", "rejected")
