"""Reconstruct legacy technology marketplace revision ``techmkt001``.

Revision ID: techmkt001
Revises: perf_listing_indexes_001
Create Date: 2026-06-27 12:00:00.000000

Root cause
----------
Render / shared Postgres has ``alembic_version.version_num = 'techmkt001'``, but
no migration file with that revision id existed in the repository. Alembic
therefore aborts before any upgrade with::

    Can't locate revision identified by 'techmkt001'

That legacy id was the technology-marketplace schema step (pricing plans +
``technology_type`` / plan columns). The same schema is also applied for
greenfield installs by ``7f3e7e682dc7``. Production continued to receive later
migrations while the version table remained on ``techmkt001``.

Why this revision is chained after the current head
---------------------------------------------------
Databases that already record ``techmkt001`` must treat that id as a reachable
head so ``alembic upgrade head`` is a no-op (schema is already present). Fresh
databases still run the full historical chain (including ``7f3e7e682dc7``) and
then execute this revision's **idempotent** ensure, which is a no-op when the
marketplace objects already exist.

This file deliberately does **not** replay the large autogenerate side-effects
from ``7f3e7e682dc7`` (table drops / mass alter_column). Only the marketplace
schema objects named by the legacy revision are ensured.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "techmkt001"
down_revision: Union[str, Sequence[str], None] = "perf_listing_indexes_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

technology_type_enum = postgresql.ENUM(
    "SOFTWARE",
    "HARDWARE",
    name="technology_type_enum",
    create_type=False,
)

technology_pricing_plan_duration_enum = postgresql.ENUM(
    "ONE_TIME",
    "ONE_MONTH",
    "THREE_MONTHS",
    "SIX_MONTHS",
    "TWELVE_MONTHS",
    name="technology_pricing_plan_duration_enum",
    create_type=False,
)


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names()):
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def _indexes(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names()):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    technology_type_enum.create(bind, checkfirst=True)
    technology_pricing_plan_duration_enum.create(bind, checkfirst=True)

    tables = _table_names()
    if "software_pricing_plans" not in tables and "software_listings" in tables:
        op.create_table(
            "software_pricing_plans",
            sa.Column("listing_id", sa.UUID(), nullable=False),
            sa.Column("plan_duration", technology_pricing_plan_duration_enum, nullable=False),
            sa.Column("price", sa.Float(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["listing_id"],
                ["software_listings.id"],
                name=op.f("fk_software_pricing_plans_listing_id_software_listings"),
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_software_pricing_plans")),
        )

    if "software_pricing_plans" in _table_names():
        if "idx_software_pricing_plans_listing_id" not in _indexes("software_pricing_plans"):
            op.create_index(
                "idx_software_pricing_plans_listing_id",
                "software_pricing_plans",
                ["listing_id"],
                unique=False,
            )

    if "software_listings" in _table_names():
        listing_cols = _columns("software_listings")
        if "documentation_urls" not in listing_cols:
            op.add_column(
                "software_listings",
                sa.Column("documentation_urls", sa.Text(), nullable=True),
            )
        if "download_urls" not in listing_cols:
            op.add_column(
                "software_listings",
                sa.Column("download_urls", sa.Text(), nullable=True),
            )
        if "technology_type" not in listing_cols:
            op.add_column(
                "software_listings",
                sa.Column(
                    "technology_type",
                    technology_type_enum,
                    nullable=False,
                    server_default="SOFTWARE",
                ),
            )

    if "software_purchases" in _table_names():
        purchase_cols = _columns("software_purchases")
        if "payout_reminder_sent_at" not in purchase_cols:
            op.add_column(
                "software_purchases",
                sa.Column("payout_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
            )
        if "payout_reminder_count" not in purchase_cols:
            op.add_column(
                "software_purchases",
                sa.Column(
                    "payout_reminder_count",
                    sa.SmallInteger(),
                    server_default="0",
                    nullable=False,
                ),
            )
        if "selected_plan" not in purchase_cols:
            op.add_column(
                "software_purchases",
                sa.Column("selected_plan", technology_pricing_plan_duration_enum, nullable=True),
            )
        if "expiry_date" not in purchase_cols:
            op.add_column(
                "software_purchases",
                sa.Column("expiry_date", sa.DateTime(timezone=True), nullable=True),
            )
        if "expiry_reminder_sent_at" not in purchase_cols:
            op.add_column(
                "software_purchases",
                sa.Column(
                    "expiry_reminder_sent_at",
                    sa.DateTime(timezone=True),
                    nullable=True,
                ),
            )


def downgrade() -> None:
    # Compatibility head — do not tear down marketplace schema that other
    # historical revisions (7f3e7e682dc7) and live data depend on.
    return
