"""Add soft-delete columns to domain_enquiries.

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-07-01 14:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h8i9j0k1l2m3"
down_revision: Union[str, Sequence[str], None] = "g7h8i9j0k1l2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "domain_enquiries"

COLUMNS: list[tuple[str, sa.Column]] = [
    ("is_deleted", sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false())),
    ("deleted_at", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)),
    ("deleted_by", sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True)),
]


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    for column_name, column in COLUMNS:
        if not _column_exists(TABLE, column_name):
            op.add_column(TABLE, column)

    op.execute(
        f"UPDATE {TABLE} SET is_deleted = FALSE WHERE is_deleted IS NULL"
    )


def downgrade() -> None:
    for column_name, _ in reversed(COLUMNS):
        if _column_exists(TABLE, column_name):
            op.drop_column(TABLE, column_name)
