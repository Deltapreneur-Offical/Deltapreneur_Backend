"""Store listing commission breakdown without buyer price markup.

Revision ID: r7s8t9u0v1w2
Revises: q6r7s8t9u0v1
Create Date: 2026-06-11 19:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "r7s8t9u0v1w2"
down_revision: Union[str, Sequence[str], None] = "q6r7s8t9u0v1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("domain_listings", sa.Column("listing_price", sa.Float(), nullable=True))
    op.add_column("domain_listings", sa.Column("commission_percentage", sa.Float(), nullable=True))
    op.add_column("domain_listings", sa.Column("commission_amount", sa.Float(), nullable=True))
    op.add_column("domain_listings", sa.Column("seller_payout_amount", sa.Float(), nullable=True))

    op.execute(
        """
        UPDATE domain_listings
        SET
            listing_price = CASE
                WHEN seller_price IS NOT NULL AND seller_price >= 0 THEN seller_price
                ELSE asking_price
            END,
            commission_percentage = CASE
                WHEN sale_type = 'ONE_TIME' AND COALESCE(seller_price, asking_price, 0) > 0 THEN 15
                ELSE NULL
            END
        """
    )
    op.execute(
        """
        UPDATE domain_listings
        SET
            commission_amount = CASE
                WHEN commission_percentage IS NOT NULL THEN ROUND((listing_price * commission_percentage / 100.0)::numeric, 2)::double precision
                ELSE NULL
            END,
            seller_payout_amount = CASE
                WHEN commission_percentage IS NOT NULL THEN ROUND((listing_price - (listing_price * commission_percentage / 100.0))::numeric, 2)::double precision
                ELSE NULL
            END
        """
    )
    op.execute(
        """
        UPDATE domain_listings
        SET
            asking_price = listing_price,
            seller_price = seller_payout_amount
        WHERE
            sale_type = 'ONE_TIME'
            AND listing_price IS NOT NULL
            AND payment_status IS DISTINCT FROM 'COMPLETED'
        """
    )


def downgrade() -> None:
    op.drop_column("domain_listings", "seller_payout_amount")
    op.drop_column("domain_listings", "commission_amount")
    op.drop_column("domain_listings", "commission_percentage")
    op.drop_column("domain_listings", "listing_price")
