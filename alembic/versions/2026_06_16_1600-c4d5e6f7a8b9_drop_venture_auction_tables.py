"""Drop legacy venture auction tables and columns.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-06-16 16:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE ventures SET sale_type = 'REGULAR' "
        "WHERE sale_type = 'AUCTION'"
    )

    op.drop_column("venture_acquisition_applications", "winning_bid_id")
    op.drop_column("venture_acquisition_applications", "venture_auction_id")

    op.drop_table("venture_auction_bids")
    op.drop_table("venture_auction_participations")
    op.drop_table("venture_auctions")

    op.drop_column("ventures", "auction_min_bid_price")
    op.drop_column("ventures", "auction_duration")


def downgrade() -> None:
    raise NotImplementedError(
        "Venture auction schema was removed; restore from backup to roll back."
    )
