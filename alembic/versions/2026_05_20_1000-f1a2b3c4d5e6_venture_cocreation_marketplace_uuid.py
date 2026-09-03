"""venture cocreation marketplace uuid modules

Revision ID: f1a2b3c4d5e6
Revises: 673e28543ac5
Create Date: 2026-05-20 10:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "673e28543ac5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _soft_delete_columns() -> list[sa.Column]:
    return [
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # Drop legacy integer-PK venture tables if present (pre-UUID migration).
    for table in ("co_venture", "venture", "venture_roles", "agreement", "contact_info", "brand_details"):
        if table in existing:
            op.drop_table(table)

    # Enums
    for name, values in (
        ("industry_enum", (
            "TECH", "FINANCE", "HEALTHCARE", "EDUCATION", "FOOD_AND_BEVERAGE",
            "RETAIL", "REAL_ESTATE", "MEDIA", "MANUFACTURING", "LOGISTICS",
            "AGRICULTURE", "SAAS", "ECOMMERCE", "SERVICES", "AI_AUTOMATION",
            "FINTECH", "OTHER",
        )),
        ("venture_type_enum", (
            "FIFTY_FIFTY", "SIXTY_FORTY", "SEVENTY_THIRTY", "EIGHTY_TWENTY",
            "NINETY_TEN", "NEGOTIABLE",
        )),
        ("venture_stage_enum", ("IDEA", "MVP", "REVENUE_GENERATING", "SCALING")),
        ("venture_sale_type_enum", ("REGULAR", "AUCTION")),
        ("venture_auction_duration_enum", (
            "ONE_DAY", "SEVEN_DAYS", "FIFTEEN_DAYS", "THIRTY_DAYS",
        )),
        ("co_venture_status_enum", ("PENDING", "APPROVED", "REJECTED")),
        ("domain_category_enum", (
            "BRANDABLE", "PREMIUM", "GENERIC", "GEOGRAPHIC", "NUMERIC", "OTHER",
        )),
        ("domain_listing_status_enum", ("AVAILABLE", "SOLD", "PENDING")),
        ("pricing_demand_enum", ("NEGOTIABLE", "FIXED")),
        ("marketplace_payment_status_enum", ("CREATED", "COMPLETED", "FAILED")),
        ("verification_method_enum", ("DNS", "WHOIS_EMAIL")),
        ("sale_type_enum", ("ONE_TIME", "AUCTION")),
        ("software_category_enum", (
            "WEB_APP", "MOBILE_APP", "SAAS", "API", "PLUGIN", "TEMPLATE", "OTHER",
        )),
        ("software_pricing_demand_enum", ("NEGOTIABLE", "FIXED")),
        ("software_status_enum", ("AVAILABLE", "SOLD", "PENDING")),
        ("software_purchase_type_enum", ("ONE_TIME", "SUBSCRIPTION")),
        ("cobrother_request_type_enum", (
            "COVENTURE", "DOMAIN", "COCREATION", "DOMAIN_ENQUIRY",
        )),
        ("cobrother_request_status_enum", (
            "PENDING", "FORWARDED", "ACCEPTED", "REJECTED", "CANCELLED",
        )),
    ):
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    op.create_table(
        "brand_details",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("brand_name", sa.String(255), nullable=True),
        sa.Column("website", sa.String(512), nullable=True),
        sa.Column("video_url", sa.String(512), nullable=True),
        sa.Column("industry", postgresql.ENUM(name="industry_enum", create_type=False), nullable=True),
        sa.Column("deal_value", sa.BigInteger(), nullable=True),
        sa.Column("venture_image_url", sa.String(1024), nullable=True),
        sa.Column("venture_type", postgresql.ENUM(name="venture_type_enum", create_type=False), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brand_details")),
    )

    op.create_table(
        "contact_info",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone_number", sa.String(32), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_info")),
    )

    op.create_table(
        "agreement",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terms", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agreement")),
    )

    op.create_table(
        "ventures",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        *_soft_delete_columns(),
        sa.Column("brand_details_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_info_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agreement_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("views", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("co_venture_application_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("listed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("purchased_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("stage", postgresql.ENUM(name="venture_stage_enum", create_type=False), nullable=True),
        sa.Column("current_problem", sa.Text(), nullable=True),
        sa.Column("taken_down", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("take_down_reason", sa.Text(), nullable=True),
        sa.Column("sale_type", postgresql.ENUM(name="venture_sale_type_enum", create_type=False), nullable=False),
        sa.Column("auction_min_bid_price", sa.Float(), nullable=True),
        sa.Column(
            "auction_duration",
            postgresql.ENUM(name="venture_auction_duration_enum", create_type=False),
            nullable=True,
        ),
        sa.Column("gstin", sa.String(15), nullable=True),
        sa.Column("gstin_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("gstin_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gstin_legal_name", sa.String(512), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("featured", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["agreement_id"], ["agreement.id"], name=op.f("fk_ventures_agreement_id_agreement")),
        sa.ForeignKeyConstraint(["brand_details_id"], ["brand_details.id"], name=op.f("fk_ventures_brand_details_id_brand_details")),
        sa.ForeignKeyConstraint(["contact_info_id"], ["contact_info.id"], name=op.f("fk_ventures_contact_info_id_contact_info")),
        sa.ForeignKeyConstraint(["listed_by_user_id"], ["users.id"], name=op.f("fk_ventures_listed_by_user_id_users")),
        sa.ForeignKeyConstraint(["purchased_by_user_id"], ["users.id"], name=op.f("fk_ventures_purchased_by_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ventures")),
    )
    op.create_index("idx_ventures_listed_by_user_id", "ventures", ["listed_by_user_id"])

    op.create_table(
        "venture_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("venture_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(64), nullable=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("skill_domain", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("commitment", sa.String(128), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("experience_level", sa.String(64), nullable=True),
        sa.Column("equity_min", sa.Float(), nullable=True),
        sa.Column("equity_max", sa.Float(), nullable=True),
        sa.Column("vesting_terms", sa.String(512), nullable=True),
        sa.Column("salary_min", sa.Float(), nullable=True),
        sa.Column("salary_max", sa.Float(), nullable=True),
        sa.Column("budget_min", sa.Float(), nullable=True),
        sa.Column("budget_max", sa.Float(), nullable=True),
        sa.Column("investment_min", sa.Float(), nullable=True),
        sa.Column("investment_max", sa.Float(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(["venture_id"], ["ventures.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_venture_roles")),
    )

    op.create_table(
        "co_ventures",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("venture_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("applicant_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", postgresql.ENUM(name="co_venture_status_enum", create_type=False), nullable=False),
        sa.ForeignKeyConstraint(["venture_id"], ["ventures.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["applicant_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("venture_id", "applicant_user_id", name="uq_coventure_venture_applicant"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_co_ventures")),
    )

    op.create_table(
        "domain_listings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        *_soft_delete_columns(),
        sa.Column("domain_name", sa.String(255), nullable=False),
        sa.Column("domain_extension", sa.String(32), nullable=False),
        sa.Column("domain_category", postgresql.ENUM(name="domain_category_enum", create_type=False), nullable=True),
        sa.Column("asking_price", sa.Float(), nullable=False),
        sa.Column("pricing_demand", postgresql.ENUM(name="pricing_demand_enum", create_type=False), nullable=True),
        sa.Column("domain_status", postgresql.ENUM(name="domain_listing_status_enum", create_type=False), nullable=False),
        sa.Column("contact_info_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agreement_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("logo", sa.String(1024), nullable=True),
        sa.Column("status", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("views", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("razorpay_order_id", sa.String(128), nullable=True),
        sa.Column("razorpay_payment_id", sa.String(128), nullable=True),
        sa.Column("payment_status", postgresql.ENUM(name="marketplace_payment_status_enum", create_type=False), nullable=True),
        sa.Column("listed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("purchased_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("verification_token", sa.String(128), nullable=True),
        sa.Column("verification_method", postgresql.ENUM(name="verification_method_enum", create_type=False), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("whois_email", sa.String(255), nullable=True),
        sa.Column("taken_down", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("take_down_reason", sa.Text(), nullable=True),
        sa.Column("sale_type", postgresql.ENUM(name="sale_type_enum", create_type=False), nullable=False),
        sa.Column("featured", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["contact_info_id"], ["contact_info.id"]),
        sa.ForeignKeyConstraint(["agreement_id"], ["agreement.id"]),
        sa.ForeignKeyConstraint(["listed_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["purchased_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_domain_listings")),
    )

    op.create_table(
        "software_listings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        *_soft_delete_columns(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("video_link", sa.String(512), nullable=True),
        sa.Column("what_it_does", sa.Text(), nullable=True),
        sa.Column("how_it_helps", sa.Text(), nullable=True),
        sa.Column("github_link", sa.String(512), nullable=True),
        sa.Column("image_url", sa.String(1024), nullable=True),
        sa.Column("live_demo_link", sa.String(512), nullable=True),
        sa.Column("tech_stack", sa.String(512), nullable=True),
        sa.Column("category", postgresql.ENUM(name="software_category_enum", create_type=False), nullable=True),
        sa.Column("pricing_demand", postgresql.ENUM(name="software_pricing_demand_enum", create_type=False), nullable=True),
        sa.Column("price", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("software_status", postgresql.ENUM(name="software_status_enum", create_type=False), nullable=False),
        sa.Column("purchase_type", postgresql.ENUM(name="software_purchase_type_enum", create_type=False), nullable=False),
        sa.Column("status", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("views", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("taken_down", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("take_down_reason", sa.Text(), nullable=True),
        sa.Column("official", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("featured", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("agreement_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("listed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["agreement_id"], ["agreement.id"]),
        sa.ForeignKeyConstraint(["listed_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_software_listings")),
    )

    op.create_table(
        "cobrother_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_type", postgresql.ENUM(name="cobrother_request_type_enum", create_type=False), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_snapshot", sa.Text(), nullable=True),
        sa.Column("assigned_cobrother_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("admin_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", postgresql.ENUM(name="cobrother_request_status_enum", create_type=False), nullable=False),
        sa.Column("response_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["assigned_cobrother_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["admin_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cobrother_requests")),
    )


def downgrade() -> None:
    op.drop_table("cobrother_requests")
    op.drop_table("software_listings")
    op.drop_table("domain_listings")
    op.drop_table("co_ventures")
    op.drop_table("venture_roles")
    op.drop_table("ventures")
    op.drop_table("agreement")
    op.drop_table("contact_info")
    op.drop_table("brand_details")
