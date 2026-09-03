"""be_cobrother_applications table

Revision ID: f6a7b8c9d0e1
Revises: ee3232f7a617
Create Date: 2026-05-31 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "ee3232f7a617"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "be_cobrother_applications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone_number", sa.String(length=32), nullable=True),
        sa.Column("pin_code", sa.String(length=50), nullable=True),
        sa.Column("skill", sa.String(length=100), nullable=True),
        sa.Column("equipment", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_be_cobrother_applications")),
    )
    op.create_index(
        op.f("ix_be_cobrother_applications_email"),
        "be_cobrother_applications",
        ["email"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_be_cobrother_applications_email"),
        table_name="be_cobrother_applications",
    )
    op.drop_table("be_cobrother_applications")
