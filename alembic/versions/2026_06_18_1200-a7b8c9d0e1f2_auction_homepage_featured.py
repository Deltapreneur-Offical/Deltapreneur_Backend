"""Add homepage featured flag to auction tables.

Revision ID: f2g3h4i5j6k7
Revises: 2034e751a117
Create Date: 2026-06-18 12:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "f2g3h4i5j6k7"
down_revision: Union[str, Sequence[str], None] = "2034e751a117"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_AUCTION_TABLES = ("auctions", "community_auctions", "software_auctions")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for table in _AUCTION_TABLES:
        columns = {col["name"] for col in inspector.get_columns(table)}
        if "featured" not in columns:
            op.add_column(
                table,
                sa.Column(
                    "featured",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("false"),
                ),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for table in _AUCTION_TABLES:
        columns = {col["name"] for col in inspector.get_columns(table)}
        if "featured" in columns:
            op.drop_column(table, "featured")
