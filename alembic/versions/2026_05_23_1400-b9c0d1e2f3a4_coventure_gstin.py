"""Add co_ventures.gstin for optional applicant GSTIN

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-05-23 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "co_ventures",
        sa.Column("gstin", sa.String(length=15), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("co_ventures", "gstin")
