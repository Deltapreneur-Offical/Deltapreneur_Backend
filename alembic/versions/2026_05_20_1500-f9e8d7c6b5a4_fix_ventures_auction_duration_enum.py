"""Fix ventures.auction_duration column to use venture_auction_duration_enum.

Revision ID: f9e8d7c6b5a4
Revises: d3e4f5a6b7c8
Create Date: 2026-05-20 15:00:00.000000

Existing databases created before f1a2b3c4d5e6 was corrected stored
ventures.auction_duration as auction_duration_enum (domain auction values).
The ORM expects venture_auction_duration_enum.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "f9e8d7c6b5a4"
down_revision: Union[str, Sequence[str], None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VENTURE_DURATION_VALUES = ("ONE_DAY", "SEVEN_DAYS", "FIFTEEN_DAYS", "THIRTY_DAYS")


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'venture_auction_duration_enum'
            ) THEN
                CREATE TYPE venture_auction_duration_enum AS ENUM (
                    'ONE_DAY', 'SEVEN_DAYS', 'FIFTEEN_DAYS', 'THIRTY_DAYS'
                );
            END IF;
        END
        $$;
        """
    )

    # Only alter if column still uses the wrong enum (legacy installs).
    op.execute(
        """
        DO $$
        DECLARE
            col_type text;
        BEGIN
            SELECT udt_name INTO col_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'ventures'
              AND column_name = 'auction_duration';

            IF col_type = 'auction_duration_enum' THEN
                ALTER TABLE ventures
                ALTER COLUMN auction_duration TYPE venture_auction_duration_enum
                USING (
                    CASE auction_duration::text
                        WHEN 'ONE_DAY' THEN 'ONE_DAY'::venture_auction_duration_enum
                        WHEN 'SEVEN_DAYS' THEN 'SEVEN_DAYS'::venture_auction_duration_enum
                        ELSE NULL
                    END
                );
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            col_type text;
        BEGIN
            SELECT udt_name INTO col_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'ventures'
              AND column_name = 'auction_duration';

            IF col_type = 'venture_auction_duration_enum' THEN
                ALTER TABLE ventures
                ALTER COLUMN auction_duration TYPE auction_duration_enum
                USING (
                    CASE auction_duration::text
                        WHEN 'ONE_DAY' THEN 'ONE_DAY'::auction_duration_enum
                        WHEN 'SEVEN_DAYS' THEN 'SEVEN_DAYS'::auction_duration_enum
                        ELSE NULL
                    END
                );
            END IF;
        END
        $$;
        """
    )
