"""virtual_assistant_applications table

Revision ID: v1a2b3c4d5e6
Revises: ed33c8d68ba2
Create Date: 2026-07-17 15:37:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "ac0c34ac14f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "virtual_assistant_applications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone_number", sa.String(length=32), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("profile_photo_url", sa.String(length=500), nullable=True),
        sa.Column("is_adult", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("bio", sa.String(length=1000), nullable=True),
        sa.Column("roles", sa.String(length=500), nullable=True),
        sa.Column("skills", sa.String(length=500), nullable=True),
        sa.Column("years_of_experience", sa.String(length=50), nullable=True),
        sa.Column("languages", sa.String(length=300), nullable=True),
        sa.Column("linkedin_url", sa.String(length=500), nullable=True),
        sa.Column("portfolio_url", sa.String(length=500), nullable=True),
        sa.Column("resume_url", sa.String(length=500), nullable=True),
        sa.Column("availability", sa.String(length=50), nullable=True),
        sa.Column("hours_per_week", sa.String(length=50), nullable=True),
        sa.Column("expected_compensation", sa.String(length=100), nullable=True),
        sa.Column("info_accurate", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("agree_terms", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(length=50), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("reference_number", sa.String(length=50), nullable=False),
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
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_virtual_assistant_applications")),
    )
    op.create_index(
        op.f("ix_virtual_assistant_applications_email"),
        "virtual_assistant_applications",
        ["email"],
        unique=False,
    )
    op.create_index(
        op.f("ix_virtual_assistant_applications_reference_number"),
        "virtual_assistant_applications",
        ["reference_number"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_virtual_assistant_applications_reference_number"),
        table_name="virtual_assistant_applications",
    )
    op.drop_index(
        op.f("ix_virtual_assistant_applications_email"),
        table_name="virtual_assistant_applications",
    )
    op.drop_table("virtual_assistant_applications")
