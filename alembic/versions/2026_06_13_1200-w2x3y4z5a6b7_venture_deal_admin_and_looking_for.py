"""Venture deal admin approval, looking_for, acquisition flow migration.

- venture_deal_status_enum += PENDING_ADMIN_APPROVAL
- venture_listing_approval_status_enum += DRAFT (optional draft state)
- ventures.looking_for TEXT column
- FULL_ACQUISITION listings: DIRECT_BUY -> SELLER_SELECTS
- Backfill CO_VENTURE equity_percent_offered from brand_details.venture_type

Revision ID: w2x3y4z5a6b7
Revises: p1c2v3f4a5b6
Create Date: 2026-06-13 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "w2x3y4z5a6b7"
down_revision: Union[str, Sequence[str], None] = "p1c2v3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    op.execute(
        "ALTER TYPE venture_deal_status_enum "
        "ADD VALUE IF NOT EXISTS 'PENDING_ADMIN_APPROVAL'"
    )
    op.execute(
        "ALTER TYPE venture_listing_approval_status_enum "
        "ADD VALUE IF NOT EXISTS 'DRAFT'"
    )

    if not _column_exists("ventures", "looking_for"):
        op.add_column("ventures", sa.Column("looking_for", sa.Text(), nullable=True))

    op.execute(
        """
        UPDATE ventures
        SET acquisition_flow = 'SELLER_SELECTS'
        WHERE deal_type = 'FULL_ACQUISITION'
          AND acquisition_flow = 'DIRECT_BUY'
        """
    )

    op.execute(
        """
        UPDATE ventures v
        SET equity_percent_offered = CASE bd.venture_type::text
          WHEN 'FIFTY_FIFTY' THEN 50
          WHEN 'SIXTY_FORTY' THEN 40
          WHEN 'SEVENTY_THIRTY' THEN 30
          WHEN 'EIGHTY_TWENTY' THEN 20
          WHEN 'NINETY_TEN' THEN 10
          ELSE NULL
        END
        FROM brand_details bd
        WHERE v.brand_details_id = bd.id
          AND v.listing_mode = 'CO_VENTURE'
          AND v.equity_percent_offered IS NULL
          AND bd.venture_type IS NOT NULL
        """
    )


def downgrade() -> None:
    if _column_exists("ventures", "looking_for"):
        op.drop_column("ventures", "looking_for")
