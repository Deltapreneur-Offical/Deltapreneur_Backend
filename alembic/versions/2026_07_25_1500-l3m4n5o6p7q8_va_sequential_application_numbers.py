"""Add sequential VA application numbers and CB-VA reference format.

Revision ID: va25seq0001
Revises: va25assign0001
Create Date: 2026-07-25 15:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision: str = "va25seq0001"
down_revision: Union[str, Sequence[str], None] = "va25assign0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEQUENCE = "va_application_number_seq"
_PREFIX = "CB-VA-"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("virtual_assistant_applications")}

    op.execute(sa.text(f"CREATE SEQUENCE IF NOT EXISTS {_SEQUENCE} START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1"))

    if "application_number" not in columns:
        op.add_column(
            "virtual_assistant_applications",
            sa.Column("application_number", sa.Integer(), nullable=True),
        )

    rows = bind.execute(
        text(
            """
            SELECT id
            FROM virtual_assistant_applications
            ORDER BY created_at ASC NULLS LAST, id ASC
            """
        )
    ).fetchall()

    for index, row in enumerate(rows, start=1):
        bind.execute(
            text(
                """
                UPDATE virtual_assistant_applications
                SET application_number = :application_number,
                    reference_number = :reference_number
                WHERE id = :id
                """
            ),
            {
                "id": row.id,
                "application_number": index,
                "reference_number": f"{_PREFIX}{index:06d}",
            },
        )

    if rows:
        bind.execute(text(f"SELECT setval('{_SEQUENCE}', (SELECT MAX(application_number) FROM virtual_assistant_applications))"))

    op.alter_column("virtual_assistant_applications", "application_number", nullable=False)
    op.create_index(
        "ix_virtual_assistant_applications_application_number",
        "virtual_assistant_applications",
        ["application_number"],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = {idx["name"] for idx in inspector.get_indexes("virtual_assistant_applications")}
    if "ix_virtual_assistant_applications_application_number" in indexes:
        op.drop_index(
            "ix_virtual_assistant_applications_application_number",
            table_name="virtual_assistant_applications",
        )

    columns = {col["name"] for col in inspector.get_columns("virtual_assistant_applications")}
    if "application_number" in columns:
        op.drop_column("virtual_assistant_applications", "application_number")

    op.execute(sa.text(f"DROP SEQUENCE IF EXISTS {_SEQUENCE}"))
