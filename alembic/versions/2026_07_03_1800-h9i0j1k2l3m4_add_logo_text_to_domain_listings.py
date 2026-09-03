"""Add logo_text to domain_listings

Revision ID: h9i0j1k2l3m4
Revises: h8i9j0k1l2m3
Create Date: 2026-07-03 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "h9i0j1k2l3m4"
down_revision: Union[str, Sequence[str], None] = "h8i9j0k1l2m3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "domain_listings"

def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if not _column_exists(TABLE, "logo_text"):
        op.add_column(TABLE, sa.Column("logo_text", sa.String(length=255), nullable=True))


def downgrade() -> None:
    if _column_exists(TABLE, "logo_text"):
        op.drop_column(TABLE, "logo_text")
