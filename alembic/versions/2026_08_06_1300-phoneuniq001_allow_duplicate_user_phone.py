"""Allow the same phone number on multiple user accounts.

Revision ID: phoneuniq001
Revises: buyergst001
Create Date: 2026-08-06 13:00:00
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


revision: str = "phoneuniq001"
down_revision: Union[str, Sequence[str], None] = "buyergst001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    constraints = {
        c["name"] for c in inspector.get_unique_constraints("users")
    }
    if "uq_users_phone_number" in constraints:
        op.drop_constraint("uq_users_phone_number", "users", type_="unique")

    indexes = {idx["name"] for idx in inspector.get_indexes("users")}
    if "idx_user_phone_number" not in indexes:
        op.create_index("idx_user_phone_number", "users", ["phone_number"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    constraints = {
        c["name"] for c in inspector.get_unique_constraints("users")
    }
    if "uq_users_phone_number" not in constraints:
        op.create_unique_constraint(
            "uq_users_phone_number",
            "users",
            ["phone_number"],
        )
