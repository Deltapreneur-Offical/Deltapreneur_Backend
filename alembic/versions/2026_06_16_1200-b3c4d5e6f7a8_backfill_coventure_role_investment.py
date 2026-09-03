"""Backfill co-venture role investment/equity from profile and venture snapshots.

Revision ID: b3c4d5e6f7a8
Revises: z2a3b4c5d6e7
Create Date: 2026-06-16 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "z2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE venture_roles vr
            SET equity_min = v.equity_percent_offered,
                equity_max = v.equity_percent_offered
            FROM ventures v
            WHERE vr.venture_id = v.id
              AND v.listing_mode = 'CO_VENTURE'
              AND vr.equity_min IS NULL
              AND v.equity_percent_offered IS NOT NULL
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE venture_roles vr
            SET investment_min = bd.seller_deal_value,
                investment_max = bd.seller_deal_value
            FROM ventures v
            JOIN brand_details bd ON bd.id = v.brand_details_id
            WHERE vr.venture_id = v.id
              AND v.listing_mode = 'CO_VENTURE'
              AND vr.investment_min IS NULL
              AND bd.seller_deal_value IS NOT NULL
              AND bd.seller_deal_value >= 0
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE venture_roles vr
            SET investment_min = bd.deal_value,
                investment_max = bd.deal_value
            FROM ventures v
            JOIN brand_details bd ON bd.id = v.brand_details_id
            WHERE vr.venture_id = v.id
              AND v.listing_mode = 'CO_VENTURE'
              AND vr.investment_min IS NULL
              AND bd.deal_value IS NOT NULL
              AND bd.deal_value >= 0
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE venture_roles vr
            SET investment_min = vcp.valuation_inr,
                investment_max = vcp.valuation_inr
            FROM ventures v
            JOIN venture_company_profiles vcp ON vcp.venture_id = v.id
            WHERE vr.venture_id = v.id
              AND v.listing_mode = 'CO_VENTURE'
              AND vr.investment_min IS NULL
              AND vcp.valuation_inr IS NOT NULL
              AND vcp.valuation_inr >= 0
            """
        )
    )


def downgrade() -> None:
    # Data repair — no safe automatic rollback.
    pass
