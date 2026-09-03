"""Drop orphaned venture auction enums and platform settings.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-06-16 17:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VENTURE_AUCTION_ENUMS = (
    "venture_auction_duration_enum",
    "venture_auction_approval_status_enum",
    "venture_auction_participation_status_enum",
    "venture_auction_seller_outcome_enum",
)


def upgrade() -> None:
    op.execute(
        "DELETE FROM platform_settings WHERE setting_key IN "
        "('venture_auction_participation_fee_inr', 'venture_auction_max_bid_inr')"
    )

    for enum_name in _VENTURE_AUCTION_ENUMS:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")


def downgrade() -> None:
    raise NotImplementedError(
        "Venture auction enums/settings cleanup cannot be rolled back automatically."
    )
