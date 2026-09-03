"""Add zone to hub_registrar_offices.

Revision ID: hubreg002
Revises: hubreg001
Create Date: 2026-08-21 12:00:00.000000

SAFETY: additive only - adds one column with server_default=0.
Existing rows receive zone=0. No data modified, no columns dropped.
downgrade() drops only this column.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "hubreg002"
down_revision: Union[str, Sequence[str], None] = "hubreg001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hub_registrar_offices",
        sa.Column(
            "zone",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("hub_registrar_offices", "zone")
