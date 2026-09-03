"""Add completion_status to software_purchases.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-25 10:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(
        "PENDING",
        "CONFIRMED",
        name="software_purchase_completion_status_enum",
    ).create(bind, checkfirst=True)

    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("software_purchases")}
    if "completion_status" not in cols:
        op.add_column(
            "software_purchases",
            sa.Column(
                "completion_status",
                postgresql.ENUM(
                    "PENDING",
                    "CONFIRMED",
                    name="software_purchase_completion_status_enum",
                    create_type=False,
                ),
                nullable=False,
                server_default="PENDING",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("software_purchases")}
    if "completion_status" in cols:
        op.drop_column("software_purchases", "completion_status")
    postgresql.ENUM(
        name="software_purchase_completion_status_enum",
    ).drop(bind, checkfirst=True)
