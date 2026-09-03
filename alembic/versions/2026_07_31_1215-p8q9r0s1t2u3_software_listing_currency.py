"""Add currency column to software_listings.

Revision ID: softcur001
Revises: opsviews001
Create Date: 2026-07-31 12:15:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "softcur001"
down_revision: Union[str, Sequence[str], None] = "opsviews001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "software_listings",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="INR"),
    )


def downgrade() -> None:
    op.drop_column("software_listings", "currency")
