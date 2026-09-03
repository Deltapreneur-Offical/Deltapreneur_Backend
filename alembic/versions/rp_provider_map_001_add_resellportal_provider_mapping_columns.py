"""add_resellportal_provider_mapping_columns

Revision ID: rp_provider_map_001
Revises: e484eeb728a2
Create Date: 2026-08-13 10:45:00.000000

Add provider mapping columns to technology_services_catalogue so each
service can declare its ResellPortal product_key and specific parameters
without hardcoding in Python.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "rp_provider_map_001"
down_revision: Union[str, Sequence[str], None] = "e484eeb728a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "technology_services_catalogue",
        sa.Column("provider_product_key", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "technology_services_catalogue",
        sa.Column("provider_specific_params", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_tech_services_provider_product_key",
        "technology_services_catalogue",
        ["provider_product_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_tech_services_provider_product_key",
        table_name="technology_services_catalogue",
    )
    op.drop_column("technology_services_catalogue", "provider_specific_params")
    op.drop_column("technology_services_catalogue", "provider_product_key")
