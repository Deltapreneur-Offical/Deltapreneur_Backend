"""Repair venture deal_value rows corrupted by legacy int() truncation (9999 → 10000).

Revision ID: z2a3b4c5d6e7
Revises: z1a2b3c4d5e6
Create Date: 2026-06-15 14:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "z2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "z1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _infer_commission_percent(deal_value: int, seller_deal_value: int | None) -> float:
    if seller_deal_value is None or deal_value <= 0:
        return 5.0
    pct = (deal_value - seller_deal_value) / float(deal_value) * 100.0
    return max(0.0, min(100.0, round(pct, 2)))


def _deductive_seller_receives(asking_price: int, commission_percent: float) -> int:
    commission = int(round(asking_price * commission_percent / 100.0))
    return asking_price - commission


def _listing_seller_payout(listing_price: int, commission_percent: float) -> int:
    commission = int(round(listing_price * commission_percent / 100.0))
    return listing_price - commission


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT
                bd.id AS brand_id,
                bd.deal_value,
                bd.seller_deal_value,
                v.listing_mode
            FROM brand_details bd
            JOIN ventures v ON v.brand_details_id = bd.id
            WHERE bd.deal_value IS NOT NULL
              AND bd.deal_value >= 9999
              AND (bd.deal_value + 1) % 10000 = 0
            """
        )
    ).mappings()

    for row in rows:
        old_deal = int(row["deal_value"])
        new_deal = old_deal + 1
        seller = row["seller_deal_value"]
        pct = _infer_commission_percent(old_deal, int(seller) if seller is not None else None)
        listing_mode = str(row["listing_mode"] or "VENTURE")

        if listing_mode == "CO_VENTURE":
            new_seller = _listing_seller_payout(new_deal, pct)
        else:
            new_seller = _deductive_seller_receives(new_deal, pct)

        conn.execute(
            sa.text(
                """
                UPDATE brand_details
                SET deal_value = :deal_value,
                    seller_deal_value = :seller_deal_value
                WHERE id = :brand_id
                """
            ),
            {
                "brand_id": row["brand_id"],
                "deal_value": new_deal,
                "seller_deal_value": new_seller,
            },
        )


def downgrade() -> None:
    # Data repair — no safe automatic rollback.
    pass
