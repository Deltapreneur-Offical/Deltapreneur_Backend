"""Add va_notifications.deleted_by for SoftDeleteMixin.

Revision ID: i1j2k3l4m5n6
Revises: h0i1j2k3l4m5
Create Date: 2026-07-23 18:05:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "i1j2k3l4m5n6"
down_revision: Union[str, Sequence[str], None] = "h0i1j2k3l4m5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    has = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='va_notifications' AND column_name='deleted_by'"
        )
    ).fetchone()
    if not has:
        op.add_column(
            "va_notifications",
            sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    has = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='va_notifications' AND column_name='deleted_by'"
        )
    ).fetchone()
    if has:
        op.drop_column("va_notifications", "deleted_by")
