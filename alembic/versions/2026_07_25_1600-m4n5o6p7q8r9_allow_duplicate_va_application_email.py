"""Allow the same email on multiple VA applications (one per role).

Revision ID: va25email0001
Revises: va25seq0001
Create Date: 2026-07-25 16:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "va25email0001"
down_revision: Union[str, Sequence[str], None] = "va25seq0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    constraints = {
        c["name"]: c for c in inspector.get_unique_constraints("virtual_assistant_applications")
    }
    if "uq_virtual_assistant_applications_email" in constraints:
        op.drop_constraint(
            "uq_virtual_assistant_applications_email",
            "virtual_assistant_applications",
            type_="unique",
        )

    indexes = {idx["name"] for idx in inspector.get_indexes("virtual_assistant_applications")}
    email_index = "ix_virtual_assistant_applications_email"
    if email_index not in indexes:
        op.create_index(email_index, "virtual_assistant_applications", ["email"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = {idx["name"] for idx in inspector.get_indexes("virtual_assistant_applications")}
    if "ix_virtual_assistant_applications_email" in indexes:
        op.drop_index("ix_virtual_assistant_applications_email", table_name="virtual_assistant_applications")

    constraints = {
        c["name"] for c in inspector.get_unique_constraints("virtual_assistant_applications")
    }
    if "uq_virtual_assistant_applications_email" not in constraints:
        op.create_unique_constraint(
            "uq_virtual_assistant_applications_email",
            "virtual_assistant_applications",
            ["email"],
        )
