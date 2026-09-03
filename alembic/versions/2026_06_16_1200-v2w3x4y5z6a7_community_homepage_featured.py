"""Add homepage featured flag to creator profiles.

Revision ID: c1d2e3f4g5h6
Revises: b3c4d5e6f7a8
Create Date: 2026-06-16 12:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "c1d2e3f4g5h6"
down_revision: Union[str, Sequence[str], None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("community")}
    if "featured" not in columns:
        op.add_column(
            "community",
            sa.Column(
                "featured",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if "cover_image_url" not in columns:
        op.add_column(
            "community",
            sa.Column("cover_image_url", sa.String(length=1000), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("community")}
    if "cover_image_url" in columns:
        op.drop_column("community", "cover_image_url")
    if "featured" in columns:
        op.drop_column("community", "featured")
