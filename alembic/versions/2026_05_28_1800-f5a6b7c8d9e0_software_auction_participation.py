"""Software auction participation fees.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-05-28 18:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, Sequence[str], None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO platform_settings (setting_key, setting_value)
        VALUES ('software_auction_participation_fee_inr', '118')
        ON CONFLICT (setting_key) DO NOTHING;
        """
    )

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE software_auction_participation_status_enum AS ENUM (
                'CREATED', 'COMPLETED', 'FAILED'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.create_table(
        "software_auction_participations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("software_auction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fee_amount_inr", sa.Float(), nullable=False),
        sa.Column("razorpay_order_id", sa.String(64), nullable=True),
        sa.Column("razorpay_payment_id", sa.String(64), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "CREATED",
                "COMPLETED",
                "FAILED",
                name="software_auction_participation_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="CREATED",
        ),
        sa.ForeignKeyConstraint(
            ["software_auction_id"],
            ["software_auctions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "software_auction_id",
            "user_id",
            name="uq_software_auction_participations_auction_user",
        ),
    )
    op.create_index(
        "idx_sap_auction_user",
        "software_auction_participations",
        ["software_auction_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_sap_auction_user", table_name="software_auction_participations")
    op.drop_table("software_auction_participations")
    op.execute("DROP TYPE IF EXISTS software_auction_participation_status_enum")
    op.execute(
        """
        DELETE FROM platform_settings
        WHERE setting_key = 'software_auction_participation_fee_inr';
        """
    )
