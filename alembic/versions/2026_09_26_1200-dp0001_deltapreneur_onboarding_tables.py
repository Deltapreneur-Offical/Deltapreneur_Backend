"""Deltapreneur onboarding: eligibility state, applications, secret invitations.

Revision ID: dp0001
Revises: techmkt002
Create Date: 2026-09-26

Creates 3 new Deltapreneur-specific tables. Strictly additive — no existing
table is altered, and the downgrade drops only these 3 tables.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "dp0001"
down_revision: Union[str, Sequence[str], None] = "techmkt002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = (
    "deltapreneur_onboarding_state",
    "deltapreneur_invitations",
    "deltapreneur_applications",
)


def _table_exists(bind, name: str) -> bool:
    return bool(
        bind.execute(
            sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :n"),
            {"n": name},
        ).first()
    )


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "deltapreneur_applications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, index=True),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("annual_revenue_inr", sa.Numeric(14, 2), nullable=False),
        sa.Column("linked_in_url", sa.String(1000), nullable=True),
        sa.Column("website_url", sa.String(1000), nullable=True),
        sa.Column("about", sa.Text(), nullable=True),
        sa.Column("motivation", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="PENDING_REVIEW",
            index=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reviewed_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    # NOTE: indexes for columns declared with ``index=True`` above (email, status)
    # are already created by ``op.create_table`` under the standard
    # ``ix_<table>_<column>`` names — do NOT create them again here.

    op.create_table(
        "deltapreneur_invitations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            UUID(as_uuid=True),
            sa.ForeignKey("deltapreneur_applications.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("token", sa.String(128), nullable=False, unique=True, index=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "used_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_admin_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    # ix_deltapreneur_invitations_token (unique) and
    # ix_deltapreneur_invitations_application_id are created by create_table
    # via ``index=True`` above — not repeated here.

    op.create_table(
        "deltapreneur_onboarding_state",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "app_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("declared_revenue_inr", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "channel",
            sa.String(32),
            nullable=False,
            server_default="SELF_DECLARED",
        ),
        sa.Column(
            "invitation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("deltapreneur_invitations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    # ix_deltapreneur_onboarding_state_app_user_id (unique) is created by
    # create_table via ``unique=True, index=True`` above — not repeated here.


def downgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        if _table_exists(bind, table):
            op.drop_table(table)
