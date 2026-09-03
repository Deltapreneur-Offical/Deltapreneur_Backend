"""software listing verification columns

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-31 14:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "software_listings",
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "software_listings",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Existing listings remain purchasable until re-reviewed; new listings start unverified.
    op.execute("UPDATE software_listings SET verified = true WHERE is_deleted = false")


def downgrade() -> None:
    op.drop_column("software_listings", "verified_at")
    op.drop_column("software_listings", "verified")
