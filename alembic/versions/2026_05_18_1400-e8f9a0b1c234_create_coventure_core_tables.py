"""create coventure core tables (brand_details, contact_info, agreement, venture)

Revision ID: e8f9a0b1c234
Revises: c7d8e9f0a123
Create Date: 2026-05-18 14:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8f9a0b1c234"
down_revision: Union[str, Sequence[str], None] = "c7d8e9f0a123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDUSTRY_VALUES = (
    "TECH",
    "FINANCE",
    "HEALTHCARE",
    "EDUCATION",
    "FOOD_AND_BEVERAGE",
    "RETAIL",
    "REAL_ESTATE",
    "MEDIA",
    "MANUFACTURING",
    "LOGISTICS",
    "AGRICULTURE",
    "SAAS",
    "ECOMMERCE",
    "SERVICES",
    "AI_AUTOMATION",
    "FINTECH",
    "OTHER",
)

_VENTURE_TYPE_VALUES = (
    "FIFTY_FIFTY",
    "SIXTY_FORTY",
    "SEVENTY_THIRTY",
    "EIGHTY_TWENTY",
    "NINETY_TEN",
    "NEGOTIABLE",
)

_VENTURE_STAGE_VALUES = ("IDEA", "MVP", "REVENUE_GENERATING", "SCALING")

_VENTURE_SALE_TYPE_VALUES = ("REGULAR", "AUCTION")

industry_enum = postgresql.ENUM(
    *_INDUSTRY_VALUES, name="industry_enum", create_type=False,
)
venture_type_enum = postgresql.ENUM(
    *_VENTURE_TYPE_VALUES, name="venture_type_enum", create_type=False,
)
venture_stage_enum = postgresql.ENUM(
    *_VENTURE_STAGE_VALUES, name="venture_stage_enum", create_type=False,
)
venture_sale_type_enum = postgresql.ENUM(
    *_VENTURE_SALE_TYPE_VALUES, name="venture_sale_type_enum", create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    industry_enum.create(bind, checkfirst=True)
    venture_type_enum.create(bind, checkfirst=True)
    venture_stage_enum.create(bind, checkfirst=True)
    venture_sale_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "brand_details",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("brand_name", sa.String(), nullable=True),
        sa.Column("website", sa.String(), nullable=True),
        sa.Column("video_url", sa.String(), nullable=True),
        sa.Column("industry", industry_enum, nullable=True),
        sa.Column("deal_value", sa.BigInteger(), nullable=True),
        sa.Column("venture_image_url", sa.String(), nullable=True),
        sa.Column("venture_type", venture_type_enum, nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brand_details")),
    )
    op.create_index(
        op.f("ix_brand_details_id"), "brand_details", ["id"], unique=False,
    )

    op.create_table(
        "contact_info",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("phone_number", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_info")),
    )
    op.create_index(
        op.f("ix_contact_info_id"), "contact_info", ["id"], unique=False,
    )

    op.create_table(
        "agreement",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("terms", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agreement")),
    )
    op.create_index(op.f("ix_agreement_id"), "agreement", ["id"], unique=False)

    op.create_table(
        "venture",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("brand_details_id", sa.Integer(), nullable=True),
        sa.Column("contact_info_id", sa.Integer(), nullable=True),
        sa.Column("agreement_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.Boolean(), nullable=True),
        sa.Column("views", sa.BigInteger(), nullable=True),
        sa.Column(
            "co_venture_application_count",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("listed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "purchased_by_user_id", postgresql.UUID(as_uuid=True), nullable=True,
        ),
        sa.Column("stage", venture_stage_enum, nullable=True),
        sa.Column("current_problem", sa.Text(), nullable=True),
        sa.Column("taken_down", sa.Boolean(), nullable=True),
        sa.Column("take_down_reason", sa.Text(), nullable=True),
        sa.Column(
            "sale_type",
            venture_sale_type_enum,
            nullable=False,
            server_default=sa.text("'REGULAR'::venture_sale_type_enum"),
        ),
        sa.Column("auction_min_bid_price", sa.Double(), nullable=True),
        sa.Column("gstin", sa.String(), nullable=True),
        sa.Column("gstin_verified", sa.Boolean(), nullable=True),
        sa.Column("gstin_verified_at", sa.DateTime(), nullable=True),
        sa.Column("gstin_legal_name", sa.String(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("featured", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(
            ["agreement_id"],
            ["agreement.id"],
            name=op.f("fk_venture_agreement_id_agreement"),
        ),
        sa.ForeignKeyConstraint(
            ["brand_details_id"],
            ["brand_details.id"],
            name=op.f("fk_venture_brand_details_id_brand_details"),
        ),
        sa.ForeignKeyConstraint(
            ["contact_info_id"],
            ["contact_info.id"],
            name=op.f("fk_venture_contact_info_id_contact_info"),
        ),
        sa.ForeignKeyConstraint(
            ["listed_by_user_id"],
            ["users.id"],
            name=op.f("fk_venture_listed_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["purchased_by_user_id"],
            ["users.id"],
            name=op.f("fk_venture_purchased_by_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_venture")),
    )


def downgrade() -> None:
    op.drop_table("venture")
    op.drop_index(op.f("ix_agreement_id"), table_name="agreement")
    op.drop_table("agreement")
    op.drop_index(op.f("ix_contact_info_id"), table_name="contact_info")
    op.drop_table("contact_info")
    op.drop_index(op.f("ix_brand_details_id"), table_name="brand_details")
    op.drop_table("brand_details")

    bind = op.get_bind()
    venture_sale_type_enum.drop(bind, checkfirst=True)
    venture_stage_enum.drop(bind, checkfirst=True)
    venture_type_enum.drop(bind, checkfirst=True)
    industry_enum.drop(bind, checkfirst=True)
