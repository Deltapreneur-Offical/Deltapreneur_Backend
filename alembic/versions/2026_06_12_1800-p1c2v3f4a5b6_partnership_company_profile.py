"""Partnership finalize, acquisition flow, and company profiles.

- venture_listing_status_enum += PARTNERSHIP_FINALIZED (co-venture partner selection,
  no payment implied)
- co_venture_status_enum += SELECTED (owner selected this partner)
- ventures.acquisition_flow (FULL_ACQUISITION sub-flow: DIRECT_BUY | SELLER_SELECTS)
- venture_company_profiles + venture_company_profile_documents tables

Revision ID: p1c2v3f4a5b6
Revises: v1a2r3c4h5r6
Create Date: 2026-06-12 18:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "p1c2v3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "v1a2r3c4h5r6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE venture_listing_status_enum "
        "ADD VALUE IF NOT EXISTS 'PARTNERSHIP_FINALIZED'"
    )
    op.execute(
        "ALTER TYPE co_venture_status_enum ADD VALUE IF NOT EXISTS 'SELECTED'"
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE venture_acquisition_flow_enum AS ENUM (
                'DIRECT_BUY', 'SELLER_SELECTS'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$;
        """
    )

    op.add_column(
        "ventures",
        sa.Column(
            "acquisition_flow",
            postgresql.ENUM(
                "DIRECT_BUY",
                "SELLER_SELECTS",
                name="venture_acquisition_flow_enum",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE ventures SET acquisition_flow = 'DIRECT_BUY'
        WHERE deal_type = 'FULL_ACQUISITION' AND acquisition_flow IS NULL
        """
    )

    op.create_table(
        "venture_company_profiles",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "venture_id",
            sa.UUID(),
            sa.ForeignKey("ventures.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("legal_entity_name", sa.String(512), nullable=True),
        sa.Column("registration_number", sa.String(128), nullable=True),
        sa.Column("incorporation_date", sa.Date(), nullable=True),
        sa.Column("company_type", sa.String(64), nullable=True),
        sa.Column("industry", sa.String(128), nullable=True),
        sa.Column("website", sa.String(512), nullable=True),
        sa.Column("business_description", sa.Text(), nullable=True),
        sa.Column("products_services", sa.Text(), nullable=True),
        sa.Column("target_market", sa.Text(), nullable=True),
        sa.Column("business_model", sa.Text(), nullable=True),
        sa.Column("annual_revenue_inr", sa.BigInteger(), nullable=True),
        sa.Column("profitability_status", sa.String(64), nullable=True),
        sa.Column("profitability_amount_inr", sa.BigInteger(), nullable=True),
        sa.Column("funding_raised_summary", sa.Text(), nullable=True),
        sa.Column("valuation_inr", sa.BigInteger(), nullable=True),
        sa.Column("market_cap_inr", sa.BigInteger(), nullable=True),
        sa.Column("founder_name", sa.String(255), nullable=True),
        sa.Column("team_size", sa.Integer(), nullable=True),
        sa.Column("key_team_members", sa.Text(), nullable=True),
        sa.Column("customer_count", sa.BigInteger(), nullable=True),
        sa.Column("user_base", sa.String(255), nullable=True),
        sa.Column("growth_metrics", sa.Text(), nullable=True),
        sa.Column("market_reach", sa.Text(), nullable=True),
        sa.Column("public_contact_person", sa.String(255), nullable=True),
        sa.Column("public_email", sa.String(320), nullable=True),
        sa.Column("public_phone_number", sa.String(32), nullable=True),
        sa.Column(
            "is_complete", sa.Boolean(), nullable=False, server_default=sa.false(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_venture_company_profiles_venture_id",
        "venture_company_profiles",
        ["venture_id"],
    )

    op.create_table(
        "venture_company_profile_documents",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.UUID(),
            sa.ForeignKey("venture_company_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_type", sa.String(64), nullable=False),
        sa.Column("file_url", sa.String(1024), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column(
            "visibility", sa.String(32), nullable=False, server_default="PUBLIC",
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_venture_company_profile_documents_profile_id",
        "venture_company_profile_documents",
        ["profile_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_venture_company_profile_documents_profile_id",
        table_name="venture_company_profile_documents",
    )
    op.drop_table("venture_company_profile_documents")
    op.drop_index(
        "idx_venture_company_profiles_venture_id",
        table_name="venture_company_profiles",
    )
    op.drop_table("venture_company_profiles")
    op.drop_column("ventures", "acquisition_flow")
    op.execute("DROP TYPE IF EXISTS venture_acquisition_flow_enum")
    # PARTNERSHIP_FINALIZED / SELECTED enum values are intentionally not removed
    # (PostgreSQL cannot drop individual enum values safely).
