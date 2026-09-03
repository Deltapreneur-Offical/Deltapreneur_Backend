"""Add software_auctions take-down columns missing from DB.

Revision ID: g9h0i1j2k3l4
Revises: f8a9b0c1d2e3
Create Date: 2026-07-23 17:45:00.000000

Coworker commit c27acd81 added ORM fields (taken_down_at, taken_down_by_id,
take_down_reason, take_down_description) without an Alembic migration.
SQLAlchemy SELECT includes those columns → UndefinedColumnError on
GET /api/v1/software-auction/active (surfaced in the browser as a CORS error
because the 500 response omits Access-Control-Allow-Origin).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "g9h0i1j2k3l4"
down_revision: Union[str, Sequence[str], None] = "f8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchall()
    return bool(rows)


def upgrade() -> None:
    if not _has_column("software_auctions", "taken_down_at"):
        op.add_column(
            "software_auctions",
            sa.Column("taken_down_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not _has_column("software_auctions", "taken_down_by_id"):
        op.add_column(
            "software_auctions",
            sa.Column(
                "taken_down_by_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if not _has_column("software_auctions", "take_down_reason"):
        op.add_column(
            "software_auctions",
            sa.Column("take_down_reason", sa.String(), nullable=True),
        )
    if not _has_column("software_auctions", "take_down_description"):
        op.add_column(
            "software_auctions",
            sa.Column("take_down_description", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    if _has_column("software_auctions", "take_down_description"):
        op.drop_column("software_auctions", "take_down_description")
    if _has_column("software_auctions", "take_down_reason"):
        op.drop_column("software_auctions", "take_down_reason")
    if _has_column("software_auctions", "taken_down_by_id"):
        op.drop_column("software_auctions", "taken_down_by_id")
    if _has_column("software_auctions", "taken_down_at"):
        op.drop_column("software_auctions", "taken_down_at")
