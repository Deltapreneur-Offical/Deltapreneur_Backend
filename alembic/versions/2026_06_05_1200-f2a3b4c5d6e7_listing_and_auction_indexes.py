"""Add browse and expiry indexes for listings and auctions.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-06-05 12:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_domain_listings_public_browse",
        "domain_listings",
        ["is_deleted", "taken_down", "status", "domain_status", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_software_listings_public_browse",
        "software_listings",
        ["is_deleted", "taken_down", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_ventures_public_browse",
        "ventures",
        ["is_deleted", "taken_down", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_community_auctions_status_end",
        "community_auctions",
        ["status", "end_time"],
        unique=False,
    )
    op.create_index(
        "idx_software_auctions_status_end",
        "software_auctions",
        ["status", "end_time"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_software_auctions_status_end", table_name="software_auctions")
    op.drop_index("idx_community_auctions_status_end", table_name="community_auctions")
    op.drop_index("idx_ventures_public_browse", table_name="ventures")
    op.drop_index("idx_software_listings_public_browse", table_name="software_listings")
    op.drop_index("idx_domain_listings_public_browse", table_name="domain_listings")
