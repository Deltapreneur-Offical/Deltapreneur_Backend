"""add soft-delete columns to technology_services_catalogue

Revision ID: a1c7f4e9d2b8
Revises: db5b099b177f
Create Date: 2026-09-05 12:20:00.000000

TechnologyServiceEntity inherits SoftDeleteMixin, which maps three columns:
is_deleted, deleted_at and deleted_by. The original create migration
(b352d8f5e27b) only created is_deleted, so every SELECT against the model
emitted deleted_at/deleted_by and failed with UndefinedColumn. The controller
swallowed that error and served the hardcoded fallback catalogue instead, so
the breakage was invisible in API responses.

Additive and idempotent: adds the two missing nullable columns only. No data
is written or removed, and no other table is touched.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "a1c7f4e9d2b8"
down_revision: Union[str, Sequence[str], None] = "db5b099b177f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "technology_services_catalogue"


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return set()
    return {col["name"] for col in inspector.get_columns(TABLE)}


def upgrade() -> None:
    columns = _existing_columns()
    if not columns:
        # Table absent (fresh DB where the create migration has not run yet on
        # this branch). Nothing to alter; the create path owns the schema.
        return

    if "deleted_at" not in columns:
        op.add_column(
            TABLE,
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "deleted_by" not in columns:
        op.add_column(
            TABLE,
            sa.Column("deleted_by", UUID(as_uuid=True), nullable=True),
        )


def downgrade() -> None:
    columns = _existing_columns()

    if "deleted_by" in columns:
        op.drop_column(TABLE, "deleted_by")

    if "deleted_at" in columns:
        op.drop_column(TABLE, "deleted_at")
