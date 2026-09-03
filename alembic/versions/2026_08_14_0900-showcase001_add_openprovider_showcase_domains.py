"""openprovider_showcase_domains table (additive, isolated).

Revision ID: showcase001
Revises: share001
Create Date: 2026-08-14

SAFETY NOTES (read before applying):
  * ADDITIVE ONLY: creates one new table. No existing table/column is
    altered, dropped, renamed, or backfilled. No existing row is touched.
  * Chains from share001 - the current single Alembic head - so the graph
    keeps exactly one head.
  * Downgrade drops only this new table.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "showcase001"
down_revision: Union[str, Sequence[str], None] = "share001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "openprovider_showcase_domains",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("domain_name", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=True),
        sa.Column("tld", sa.String(length=64), nullable=False),
        sa.Column("is_premium", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("create_price_inr", sa.Float(), nullable=True),
        sa.Column("renewal_price_inr", sa.Float(), nullable=True),
        sa.Column("payable_inr", sa.Float(), nullable=True),
        sa.Column("price_snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_selected", sa.Boolean(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.UUID(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_openprovider_showcase_domains")),
        sa.UniqueConstraint(
            "domain_name", name=op.f("uq_openprovider_showcase_domains_domain_name")
        ),
    )
    op.create_index(
        op.f("ix_openprovider_showcase_domains_domain_name"),
        "openprovider_showcase_domains",
        ["domain_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_openprovider_showcase_domains_tld"),
        "openprovider_showcase_domains",
        ["tld"],
        unique=False,
    )
    op.create_index(
        op.f("ix_openprovider_showcase_domains_is_selected"),
        "openprovider_showcase_domains",
        ["is_selected"],
        unique=False,
    )
    op.create_index(
        op.f("ix_openprovider_showcase_domains_last_checked_at"),
        "openprovider_showcase_domains",
        ["last_checked_at"],
        unique=False,
    )
    op.create_index(
        "ix_openprovider_showcase_domains_selected_tld_available",
        "openprovider_showcase_domains",
        ["is_selected", "tld", "available"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_openprovider_showcase_domains_selected_tld_available",
        table_name="openprovider_showcase_domains",
    )
    op.drop_index(
        op.f("ix_openprovider_showcase_domains_last_checked_at"),
        table_name="openprovider_showcase_domains",
    )
    op.drop_index(
        op.f("ix_openprovider_showcase_domains_is_selected"),
        table_name="openprovider_showcase_domains",
    )
    op.drop_index(
        op.f("ix_openprovider_showcase_domains_tld"),
        table_name="openprovider_showcase_domains",
    )
    op.drop_index(
        op.f("ix_openprovider_showcase_domains_domain_name"),
        table_name="openprovider_showcase_domains",
    )
    op.drop_table("openprovider_showcase_domains")
