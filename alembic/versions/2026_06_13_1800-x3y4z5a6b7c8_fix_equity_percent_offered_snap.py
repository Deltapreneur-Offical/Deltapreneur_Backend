"""Snap equity_percent_offered values stored 0.01 below whole numbers (e.g. 9.99 → 10).

Revision ID: x3y4z5a6b7c8
Revises: w2x3y4z5a6b7
Create Date: 2026-06-13 18:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "x3y4z5a6b7c8"
down_revision: Union[str, Sequence[str], None] = "w2x3y4z5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE ventures
        SET equity_percent_offered = FLOOR(equity_percent_offered) + 1
        WHERE equity_percent_offered IS NOT NULL
          AND equity_percent_offered < 100
          AND ABS(
            (equity_percent_offered - FLOOR(equity_percent_offered)) - 0.99
          ) < 0.001
        """
    )
    op.execute(
        """
        UPDATE venture_acquisition_applications
        SET equity_percent_sought = FLOOR(equity_percent_sought) + 1
        WHERE equity_percent_sought IS NOT NULL
          AND equity_percent_sought < 100
          AND ABS(
            (equity_percent_sought - FLOOR(equity_percent_sought)) - 0.99
          ) < 0.001
        """
    )
    op.execute(
        """
        UPDATE venture_deal_transactions
        SET equity_percent = FLOOR(equity_percent) + 1
        WHERE equity_percent IS NOT NULL
          AND equity_percent < 100
          AND ABS((equity_percent - FLOOR(equity_percent)) - 0.99) < 0.001
        """
    )


def downgrade() -> None:
    pass
