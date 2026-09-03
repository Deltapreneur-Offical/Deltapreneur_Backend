"""Expand domain auction durations to 1/7/30/60/90 days.

Revision ID: b1c2d3e4f5a6
Revises: 48c93a49de42
Create Date: 2026-06-25 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "48c93a49de42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'auction_duration_enum') THEN
                ALTER TYPE auction_duration_enum RENAME TO auction_duration_enum_old;
            END IF;
        END
        $$;
    """)

    op.execute("""
        CREATE TYPE auction_duration_enum AS ENUM (
            'ONE_DAY',
            'SEVEN_DAYS',
            'THIRTY_DAYS',
            'SIXTY_DAYS',
            'NINETY_DAYS'
        );
    """)

    op.execute("""
        ALTER TABLE auctions
        ALTER COLUMN duration TYPE auction_duration_enum
        USING CASE
            WHEN duration::text = 'ONE_HOUR' THEN 'ONE_DAY'::auction_duration_enum
            WHEN duration::text = 'SIX_HOURS' THEN 'SEVEN_DAYS'::auction_duration_enum
            WHEN duration::text = 'TWELVE_HOURS' THEN 'SEVEN_DAYS'::auction_duration_enum
            WHEN duration::text = 'THREE_DAYS' THEN 'SEVEN_DAYS'::auction_duration_enum
            WHEN duration::text = 'ONE_DAY' THEN 'ONE_DAY'::auction_duration_enum
            WHEN duration::text = 'SEVEN_DAYS' THEN 'SEVEN_DAYS'::auction_duration_enum
            WHEN duration::text = 'THIRTY_DAYS' THEN 'THIRTY_DAYS'::auction_duration_enum
            WHEN duration::text = 'SIXTY_DAYS' THEN 'SIXTY_DAYS'::auction_duration_enum
            WHEN duration::text = 'NINETY_DAYS' THEN 'NINETY_DAYS'::auction_duration_enum
            ELSE 'ONE_DAY'::auction_duration_enum
        END;
    """)

    op.execute("""
        DROP TYPE IF EXISTS auction_duration_enum_old;
    """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'auction_duration_enum') THEN
                ALTER TYPE auction_duration_enum RENAME TO auction_duration_enum_new;
            END IF;
        END
        $$;
    """)

    op.execute("""
        CREATE TYPE auction_duration_enum AS ENUM (
            'ONE_HOUR',
            'SIX_HOURS',
            'TWELVE_HOURS',
            'ONE_DAY',
            'THREE_DAYS',
            'SEVEN_DAYS'
        );
    """)

    op.execute("""
        ALTER TABLE auctions
        ALTER COLUMN duration TYPE auction_duration_enum
        USING CASE
            WHEN duration::text = 'ONE_DAY' THEN 'ONE_DAY'::auction_duration_enum
            WHEN duration::text = 'SEVEN_DAYS' THEN 'SEVEN_DAYS'::auction_duration_enum
            WHEN duration::text IN ('THIRTY_DAYS', 'SIXTY_DAYS', 'NINETY_DAYS') THEN 'SEVEN_DAYS'::auction_duration_enum
            ELSE 'ONE_DAY'::auction_duration_enum
        END;
    """)

    op.execute("""
        DROP TYPE IF EXISTS auction_duration_enum_new;
    """)
