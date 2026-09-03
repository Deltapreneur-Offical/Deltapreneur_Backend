"""compatibility placeholder for legacy auth hardening migration

Revision ID: c4e8f1a2b3d6
Revises: b8f2a1c3d4e5
Create Date: 2026-05-19 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e8f1a2b3d6"
down_revision: Union[str, Sequence[str], None] = "b8f2a1c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "otp",
        existing_type=sa.String(length=10),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
    op.create_index(
        "idx_user_phone_number",
        "users",
        ["phone_number"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_users_phone_number",
        "users",
        ["phone_number"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_users_phone_number", "users", type_="unique")
    op.drop_index("idx_user_phone_number", table_name="users")
    op.alter_column(
        "users",
        "otp",
        existing_type=sa.String(length=255),
        type_=sa.String(length=10),
        existing_nullable=True,
    )
