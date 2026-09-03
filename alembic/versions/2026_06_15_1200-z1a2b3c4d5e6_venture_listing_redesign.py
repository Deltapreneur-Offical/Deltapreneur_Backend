"""Venture listing redesign: revenue history, team members, verification, co-venture video.

Revision ID: z1a2b3c4d5e6
Revises: y4z5a6b7c8d9
Create Date: 2026-06-15 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "z1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "y4z5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "venture_company_profiles",
        sa.Column("current_year_revenue_inr", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "venture_company_profiles",
        sa.Column("previous_year_revenue_inr", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "venture_company_profiles",
        sa.Column("two_years_ago_revenue_inr", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "venture_company_profiles",
        sa.Column("team_members", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.execute(
        """
        UPDATE venture_company_profiles
        SET current_year_revenue_inr = annual_revenue_inr
        WHERE annual_revenue_inr IS NOT NULL
          AND current_year_revenue_inr IS NULL
        """
    )

    op.add_column(
        "ventures",
        sa.Column(
            "verification_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "ventures",
        sa.Column("verification_video_url", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "ventures",
        sa.Column(
            "verification_status",
            sa.String(length=32),
            nullable=False,
            server_default="NONE",
        ),
    )
    op.add_column(
        "ventures",
        sa.Column("verification_rejection_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "ventures",
        sa.Column("verification_reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "ventures",
        sa.Column("verification_reviewed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_ventures_verification_reviewed_by_user_id",
        "ventures",
        "users",
        ["verification_reviewed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "venture_verification_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("venture_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_url", sa.String(length=1024), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["venture_id"], ["ventures.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "idx_venture_verification_documents_venture_id",
        "venture_verification_documents",
        ["venture_id"],
    )

    op.add_column(
        "co_ventures",
        sa.Column("video_introduction_url", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("co_ventures", "video_introduction_url")
    op.drop_index("idx_venture_verification_documents_venture_id", table_name="venture_verification_documents")
    op.drop_table("venture_verification_documents")
    op.drop_constraint("fk_ventures_verification_reviewed_by_user_id", "ventures", type_="foreignkey")
    op.drop_column("ventures", "verification_reviewed_by_user_id")
    op.drop_column("ventures", "verification_reviewed_at")
    op.drop_column("ventures", "verification_rejection_reason")
    op.drop_column("ventures", "verification_status")
    op.drop_column("ventures", "verification_video_url")
    op.drop_column("ventures", "verification_requested")
    op.drop_column("venture_company_profiles", "team_members")
    op.drop_column("venture_company_profiles", "two_years_ago_revenue_inr")
    op.drop_column("venture_company_profiles", "previous_year_revenue_inr")
    op.drop_column("venture_company_profiles", "current_year_revenue_inr")
