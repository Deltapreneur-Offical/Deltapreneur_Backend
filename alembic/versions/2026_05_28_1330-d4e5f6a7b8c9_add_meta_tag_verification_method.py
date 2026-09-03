"""Add META_TAG to verification_method_enum.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-28 13:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_enum e
                JOIN pg_type t ON e.enumtypid = t.oid
                WHERE t.typname = 'verification_method_enum'
                  AND e.enumlabel = 'META_TAG'
            ) THEN
                ALTER TYPE verification_method_enum ADD VALUE 'META_TAG';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    # PostgreSQL enums cannot easily remove individual values safely.
    pass

