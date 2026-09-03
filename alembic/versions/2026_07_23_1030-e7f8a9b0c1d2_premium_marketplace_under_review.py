"""Add UNDER_REVIEW to domain listing status enum.

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-07-23 10:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ENUM ADD VALUE cannot run inside a transaction on some Postgres versions.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE domain_listing_status_enum ADD VALUE IF NOT EXISTS 'UNDER_REVIEW'"
        )


def downgrade() -> None:
    # Postgres cannot easily remove enum values; leave as no-op.
    pass
