"""add auction participations table

Revision ID: 6f7a8b9c0d1e
Revises: d4e5f6a7b8c9
Create Date: 2026-05-28 15:15:00.000000
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "6f7a8b9c0d1e"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'auction_participation_type_enum') THEN
                CREATE TYPE auction_participation_type_enum AS ENUM ('DOMAIN', 'SOFTWARE', 'COMMUNITY');
            END IF;
        END$$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'auction_participation_status_enum') THEN
                CREATE TYPE auction_participation_status_enum AS ENUM ('CREATED', 'COMPLETED', 'FAILED');
            END IF;
        END$$;
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS auction_participations (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            auction_type auction_participation_type_enum NOT NULL,
            auction_id UUID NOT NULL,
            user_id UUID NOT NULL,
            fee_amount_inr DOUBLE PRECISION NOT NULL,
            razorpay_order_id VARCHAR(64),
            razorpay_payment_id VARCHAR(64),
            status auction_participation_status_enum NOT NULL DEFAULT 'CREATED',
            CONSTRAINT uq_auction_participations_type_auction_user
                UNIQUE (auction_type, auction_id, user_id)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_auction_participation_lookup
        ON auction_participations (auction_type, auction_id, user_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_auction_participation_lookup;")
    op.execute("DROP TABLE IF EXISTS auction_participations;")
    op.execute("DROP TYPE IF EXISTS auction_participation_status_enum;")
    op.execute("DROP TYPE IF EXISTS auction_participation_type_enum;")
