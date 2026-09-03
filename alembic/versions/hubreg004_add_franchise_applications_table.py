"""Add franchise_applications table.

Revision ID: hubreg004
Revises: hubreg003
Create Date: 2026-08-24 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "hubreg004"
down_revision = "hubreg003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "franchise_applications",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("mobile_number", sa.String(20), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("state", sa.String(100), nullable=False),
        sa.Column("full_address", sa.Text, nullable=False),
        sa.Column("existing_business_name", sa.String(255), nullable=True),
        sa.Column("business_type", sa.String(100), nullable=True),
        sa.Column("preferred_location", sa.String(255), nullable=True),
        sa.Column("existing_office_availability", sa.String(100), nullable=True),
        sa.Column("relevant_experience", sa.Text, nullable=True),
        sa.Column("reason_for_applying", sa.Text, nullable=True),
        sa.Column("additional_information", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("is_blacklisted", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("blacklist_reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("idx_franchise_app_status", "franchise_applications", ["status"])
    op.create_index("idx_franchise_app_blacklisted", "franchise_applications", ["is_blacklisted"])
    op.create_index("idx_franchise_app_email", "franchise_applications", ["email"])
    op.create_index("idx_franchise_app_mobile", "franchise_applications", ["mobile_number"])


def downgrade() -> None:
    op.drop_index("idx_franchise_app_mobile", table_name="franchise_applications")
    op.drop_index("idx_franchise_app_email", table_name="franchise_applications")
    op.drop_index("idx_franchise_app_blacklisted", table_name="franchise_applications")
    op.drop_index("idx_franchise_app_status", table_name="franchise_applications")
    op.drop_table("franchise_applications")
