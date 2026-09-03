"""Recreate platform_settings table with default commission values.

Revision ID: e2f3g4h5i6j6
Revises: d1e2f3a4b5c6
Create Date: 2026-06-27 18:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e2f3g4h5i6j6"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Recreate platform_settings table
    op.execute("""
        CREATE TABLE IF NOT EXISTS platform_settings (
            setting_key VARCHAR(128) PRIMARY KEY,
            setting_value TEXT NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    
    # Seed with default commission percentages
    op.execute("""
        INSERT INTO platform_settings (setting_key, setting_value, updated_at) VALUES
        ('software_onetime_commission_percent', '15.0', NOW()),
        ('hardware_onetime_commission_percent', '15.0', NOW()),
        ('hardware_subscription_commission_percent', '20.0', NOW()),
        ('listing_commission_percent', '15.0', NOW()),
        ('venture_acquisition_commission_percent', '5.0', NOW())
        ON CONFLICT (setting_key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform_settings")
