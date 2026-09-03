"""Add homepage featured flag to virtual assistant applications.

Revision ID: va25feat0001
Revises: f684911543b7
Create Date: 2026-07-25 12:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "va25feat0001"
down_revision: Union[str, Sequence[str], None] = "f684911543b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("virtual_assistant_applications")}
    if "featured" not in columns:
        op.add_column(
            "virtual_assistant_applications",
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
    columns = {col["name"] for col in inspector.get_columns("virtual_assistant_applications")}
    if "featured" in columns:
        op.drop_column("virtual_assistant_applications", "featured")
