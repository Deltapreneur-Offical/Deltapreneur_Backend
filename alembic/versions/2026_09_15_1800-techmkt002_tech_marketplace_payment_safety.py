"""Technology marketplace payment, delivery snapshot, and payout safety.

Revision ID: techmkt002
Revises: techmkt001
Create Date: 2026-09-15 18:00:00

``techmkt001`` is reserved as the Render legacy locator no-op. Real marketplace
schema changes live here as ``techmkt002``.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "techmkt002"
down_revision: Union[str, Sequence[str], None] = "techmkt001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table
              AND column_name = :column
            LIMIT 1
            """
        ),
        {"table": table, "column": column.name},
    ).scalar()
    if exists:
        return
    op.add_column(table, column)


def upgrade() -> None:
    op.execute(
        "ALTER TYPE software_payment_status_enum ADD VALUE IF NOT EXISTS 'CANCELLED'"
    )
    op.execute(
        "ALTER TYPE software_payment_status_enum ADD VALUE IF NOT EXISTS 'REFUNDED'"
    )
    _add_column_if_missing(
        "software_listings",
        sa.Column("rejected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    _add_column_if_missing(
        "software_purchases",
        sa.Column("razorpay_refund_id", sa.String(length=128), nullable=True),
    )
    _add_column_if_missing(
        "software_purchases",
        sa.Column("refund_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "software_purchases",
        sa.Column("delivered_github_link", sa.String(length=512), nullable=True),
    )
    _add_column_if_missing(
        "software_purchases",
        sa.Column("delivered_documentation_urls", sa.Text(), nullable=True),
    )
    _add_column_if_missing(
        "software_purchases",
        sa.Column("delivered_download_urls", sa.Text(), nullable=True),
    )
    _add_column_if_missing(
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
