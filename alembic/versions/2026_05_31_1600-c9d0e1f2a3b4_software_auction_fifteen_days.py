"""Add FIFTEEN_DAYS to software auction duration enum (Java parity).

Revision ID: c9d0e1f2a3b4
Revises: b85582604c7b
Create Date: 2026-05-31 16:00:00.000000

Legacy Java software auctions stored duration as AuctionDuration
(ONE_DAY, SEVEN_DAYS, FIFTEEN_DAYS, THIRTY_DAYS). Python initially
only defined FOURTEEN_DAYS, which breaks ORM reads and admin listing.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b85582604c7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SOFTWARE_DURATION_VALUES = (
    "ONE_DAY",
    "THREE_DAYS",
    "FIVE_DAYS",
    "SEVEN_DAYS",
    "FOURTEEN_DAYS",
    "FIFTEEN_DAYS",
    "THIRTY_DAYS",
)


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'software_auction_duration_enum'
            ) THEN
                CREATE TYPE software_auction_duration_enum AS ENUM (
                    'ONE_DAY', 'THREE_DAYS', 'FIVE_DAYS', 'SEVEN_DAYS',
                    'FOURTEEN_DAYS', 'FIFTEEN_DAYS', 'THIRTY_DAYS'
                );
            END IF;
        END
        $$;
        """
    )
    op.execute(
        "ALTER TYPE software_auction_duration_enum "
        "ADD VALUE IF NOT EXISTS 'FIFTEEN_DAYS'"
    )

    # Some legacy DBs still use domain auction_duration_enum on software_auctions.
    op.execute(
        """
        DO $$
        DECLARE
            col_type text;
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'software_auctions'
            ) THEN
                RETURN;
            END IF;

            SELECT udt_name INTO col_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'software_auctions'
              AND column_name = 'duration';

            IF col_type = 'auction_duration_enum' THEN
                ALTER TABLE software_auctions
                ALTER COLUMN duration TYPE software_auction_duration_enum
                USING (
                    CASE duration::text
                        WHEN 'ONE_DAY' THEN 'ONE_DAY'::software_auction_duration_enum
                        WHEN 'THREE_DAYS' THEN 'THREE_DAYS'::software_auction_duration_enum
                        WHEN 'FIVE_DAYS' THEN 'FIVE_DAYS'::software_auction_duration_enum
                        WHEN 'SEVEN_DAYS' THEN 'SEVEN_DAYS'::software_auction_duration_enum
                        WHEN 'FOURTEEN_DAYS' THEN 'FOURTEEN_DAYS'::software_auction_duration_enum
                        WHEN 'FIFTEEN_DAYS' THEN 'FIFTEEN_DAYS'::software_auction_duration_enum
                        WHEN 'THIRTY_DAYS' THEN 'THIRTY_DAYS'::software_auction_duration_enum
                        ELSE 'SEVEN_DAYS'::software_auction_duration_enum
                    END
                );
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    # PostgreSQL cannot remove enum values safely; no-op.
    pass
