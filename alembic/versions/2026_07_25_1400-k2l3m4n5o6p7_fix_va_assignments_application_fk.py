"""Point va_assignments.application_id at virtual_assistant_applications.

Revision ID: va25assign0001
Revises: va25feat0001
Create Date: 2026-07-25 14:00:00
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


revision: str = "va25assign0001"
down_revision: Union[str, Sequence[str], None] = "va25feat0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _drop_fk_to_users() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for fk in inspector.get_foreign_keys("va_assignments"):
        if fk.get("referred_table") == "users" and "application_id" in (fk.get("constrained_columns") or []):
            op.drop_constraint(fk["name"], "va_assignments", type_="foreignkey")
            return


def upgrade() -> None:
    _drop_fk_to_users()
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = {
        (tuple(fk.get("constrained_columns") or []), fk.get("referred_table"))
        for fk in inspector.get_foreign_keys("va_assignments")
    }
    if (("application_id",), "virtual_assistant_applications") not in existing:
        op.create_foreign_key(
            "fk_va_assignments_application_id",
            "va_assignments",
            "virtual_assistant_applications",
            ["application_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for fk in inspector.get_foreign_keys("va_assignments"):
        if fk.get("referred_table") == "virtual_assistant_applications" and "application_id" in (
            fk.get("constrained_columns") or []
        ):
            op.drop_constraint(fk["name"], "va_assignments", type_="foreignkey")
            break
    op.create_foreign_key(
        "fk_va_assignments_va_id_users",
        "va_assignments",
        "users",
        ["application_id"],
        ["id"],
        ondelete="CASCADE",
    )
