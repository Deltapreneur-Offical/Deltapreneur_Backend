"""Add users.address for complete-profile

Revision ID: a8b9c0d1e2f3
Revises: 0c68f5ba7a72
Create Date: 2026-05-23 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "0c68f5ba7a72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("address", sa.String(length=150), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "address")
