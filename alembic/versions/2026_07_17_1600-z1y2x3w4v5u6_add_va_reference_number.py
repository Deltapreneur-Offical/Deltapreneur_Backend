"""Add reference_number to virtual_assistant_applications

Revision ID: z1y2x3w4v5u6
Revises: v1a2b3c4d5e6
Create Date: 2026-07-17 16:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "z1y2x3w4v5u6"
down_revision: Union[str, Sequence[str], None] = "v1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("virtual_assistant_applications")}
    indexes = {idx["name"] for idx in inspector.get_indexes("virtual_assistant_applications")}

    if "reference_number" not in columns:
        op.add_column(
            "virtual_assistant_applications",
            sa.Column("reference_number", sa.String(length=50), nullable=True),
        )
        bind.execute(
            sa.text(
                "UPDATE virtual_assistant_applications SET reference_number = 'VA-' || id::text "
                "WHERE reference_number IS NULL"
            )
        )
        op.alter_column("virtual_assistant_applications", "reference_number", nullable=False)

    index_name = op.f("ix_virtual_assistant_applications_reference_number")
    if index_name not in indexes:
        op.create_index(
            index_name,
            "virtual_assistant_applications",
            ["reference_number"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_virtual_assistant_applications_reference_number"),
        table_name="virtual_assistant_applications",
    )
    op.drop_column("virtual_assistant_applications", "reference_number")
