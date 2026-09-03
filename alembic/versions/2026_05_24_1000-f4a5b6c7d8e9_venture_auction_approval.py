"""Add venture auction admin approval (post-GSTIN gate)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None

APPROVAL_ENUM = "venture_auction_approval_status_enum"


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE venture_auction_approval_status_enum AS ENUM (
                'AWAITING_GSTIN',
                'PENDING_APPROVAL',
                'APPROVED',
                'REJECTED'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.add_column(
        "venture_auctions",
        sa.Column(
            "approval_status",
            postgresql.ENUM(
                "AWAITING_GSTIN",
                "PENDING_APPROVAL",
                "APPROVED",
                "REJECTED",
                name=APPROVAL_ENUM,
                create_type=False,
            ),
            nullable=False,
            server_default="AWAITING_GSTIN",
        ),
    )
    op.add_column(
        "venture_auctions",
        sa.Column("rejection_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_venture_auctions_approval",
        "venture_auctions",
        ["approval_status"],
    )
    op.execute(
        """
        UPDATE venture_auctions
        SET approval_status = 'APPROVED'
        WHERE status IN ('ACTIVE', 'EXTENDED', 'ENDED', 'UNSOLD');
        """
    )
    op.execute(
        """
        UPDATE venture_auctions va
        SET approval_status = 'PENDING_APPROVAL'
        FROM ventures v
        WHERE va.venture_id = v.id
          AND va.status = 'DRAFT'
          AND v.gstin_verified = true;
        """
    )


def downgrade() -> None:
    op.drop_index("idx_venture_auctions_approval", table_name="venture_auctions")
    op.drop_column("venture_auctions", "rejection_reason")
    op.drop_column("venture_auctions", "approval_status")
    op.execute("DROP TYPE IF EXISTS venture_auction_approval_status_enum")
