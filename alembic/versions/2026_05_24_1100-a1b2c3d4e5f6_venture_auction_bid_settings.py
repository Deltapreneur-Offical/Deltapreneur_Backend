"""Platform auction settings + venture auction bidder participation fees."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a1b2c3d4e5f6"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_settings",
        sa.Column("setting_key", sa.String(128), primary_key=True),
        sa.Column("setting_value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute(
        """
        INSERT INTO platform_settings (setting_key, setting_value) VALUES
        ('venture_auction_participation_fee_inr', '118'),
        ('venture_auction_max_bid_inr', '50000000')
        ON CONFLICT (setting_key) DO NOTHING;
        """
    )

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE venture_auction_participation_status_enum AS ENUM (
                'CREATED', 'COMPLETED', 'FAILED'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.create_table(
        "venture_auction_participations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("venture_auction_id", postgresql.UUID(as_uuid=True), nullable=False),
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
                name="venture_auction_participation_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="CREATED",
        ),
        sa.ForeignKeyConstraint(
            ["venture_auction_id"],
            ["venture_auctions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "venture_auction_id",
            "user_id",
            name="uq_venture_auction_participations_auction_user",
        ),
    )
    op.create_index(
        "idx_vap_auction_user",
        "venture_auction_participations",
        ["venture_auction_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_vap_auction_user", table_name="venture_auction_participations")
    op.drop_table("venture_auction_participations")
    op.execute("DROP TYPE IF EXISTS venture_auction_participation_status_enum")
    op.drop_table("platform_settings")
