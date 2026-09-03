"""operations_services catalog table and seed

Revision ID: o1p2q3r4s5t6
Revises: a1b2c3d4e5f9
Create Date: 2026-06-12 12:00:00.000000

"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "o1p2q3r4s5t6"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_DESCRIPTION = (
    "Dedicated remote professional for your MSME — flexible monthly engagement."
)

SEED_ROWS = [
    ("Virtual HR Manager", "people", 18999, "Users", "hr people hiring recruitment", 1),
    ("Virtual Accountant", "finance", 22999, "Calculator", "accounting finance books", 2),
    ("Virtual Social Media Manager", "marketing", 14999, "Share2", "social media instagram linkedin", 3),
    ("Virtual Customer Support Executive", "support", 11999, "MessageCircle", "customer support helpdesk", 4),
    ("Virtual Sales Representative", "sales", 15999, "TrendingUp", "sales leads outbound", 5),
    ("Virtual Digital Marketing Executive", "marketing", 17999, "Megaphone", "digital marketing ads campaigns", 6),
    ("Virtual Frontend Developer", "technology", 34999, "Code", "frontend react developer web", 7),
    ("Virtual Backend Developer", "technology", 34999, "Server", "backend api developer java node", 8),
    ("Virtual Full Stack Developer", "technology", 44999, "Layers", "full stack developer web app", 9),
    ("Virtual Admin Assistant", "operations", 9999, "ClipboardList", "admin assistant operations", 10),
    ("Virtual SEO Specialist", "marketing", 16999, "Search", "seo search ranking google", 11),
    ("Virtual Graphic Designer", "creative", 15499, "Palette", "graphic design branding", 12),
    ("Virtual Video Editor", "creative", 17499, "Film", "video editing reels youtube", 13),
    ("Virtual CRM Specialist", "sales", 14499, "Database", "crm hubspot salesforce pipeline", 14),
    ("Virtual Business Development Executive", "growth", 18499, "Briefcase", "business development partnerships growth", 15),
]


def upgrade() -> None:
    op.create_table(
        "operations_services",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("icon", sa.String(length=64), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skills", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operations_services")),
    )
    op.create_index(
        "idx_operations_services_public_browse",
        "operations_services",
        ["is_deleted", "is_available", "display_order"],
        unique=False,
    )
    op.create_index(
        "idx_operations_services_category",
        "operations_services",
        ["category"],
        unique=False,
    )

    now = datetime.now(timezone.utc)
    operations_services = sa.table(
        "operations_services",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("category", sa.String),
        sa.column("description", sa.Text),
        sa.column("price", sa.Float),
        sa.column("is_available", sa.Boolean),
        sa.column("icon", sa.String),
        sa.column("display_order", sa.Integer),
        sa.column("skills", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("is_deleted", sa.Boolean),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
        sa.column("deleted_by", postgresql.UUID(as_uuid=True)),
    )

    op.bulk_insert(
        operations_services,
        [
            {
                "id": uuid.uuid4(),
                "name": name,
                "category": category,
                "description": DEFAULT_DESCRIPTION,
                "price": float(price),
                "is_available": True,
                "icon": icon,
                "display_order": display_order,
                "skills": skills,
                "created_at": now,
                "updated_at": now,
                "is_deleted": False,
                "deleted_at": None,
                "deleted_by": None,
            }
            for name, category, price, icon, skills, display_order in SEED_ROWS
        ],
    )


def downgrade() -> None:
    op.drop_index("idx_operations_services_category", table_name="operations_services")
    op.drop_index("idx_operations_services_public_browse", table_name="operations_services")
    op.drop_table("operations_services")
