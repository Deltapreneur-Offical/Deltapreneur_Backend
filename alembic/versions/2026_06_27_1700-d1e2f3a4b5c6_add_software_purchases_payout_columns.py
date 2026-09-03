"""Add payout tracking columns to software_purchases.

Revision ID: d1e2f3a4b5c6
Revises: 7f3e7e682dc7
Create Date: 2026-06-27 17:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "7f3e7e682dc7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add payout tracking columns if they don't exist
    op.execute("""
        ALTER TABLE software_purchases 
        ADD COLUMN IF NOT EXISTS gross_amount_inr FLOAT DEFAULT 0.0 NOT NULL,
        ADD COLUMN IF NOT EXISTS platform_fee_inr FLOAT DEFAULT 0.0 NOT NULL,
        ADD COLUMN IF NOT EXISTS seller_payout_inr FLOAT DEFAULT 0.0 NOT NULL,
        ADD COLUMN IF NOT EXISTS payout_approved_by_user_id UUID,
        ADD COLUMN IF NOT EXISTS payout_approved_at TIMESTAMP WITH TIME ZONE,
        ADD COLUMN IF NOT EXISTS seller_paid_at TIMESTAMP WITH TIME ZONE
    """)
    # Add foreign key if it doesn't exist
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint 
                WHERE conname = 'fk_software_purchases_payout_approved_by_user_id_users'
            ) THEN
                ALTER TABLE software_purchases 
                ADD CONSTRAINT fk_software_purchases_payout_approved_by_user_id_users 
                FOREIGN KEY (payout_approved_by_user_id) REFERENCES users(id) ON DELETE SET NULL;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE software_purchases 
        DROP COLUMN IF EXISTS seller_paid_at,
        DROP COLUMN IF EXISTS payout_approved_at,
        DROP COLUMN IF EXISTS payout_approved_by_user_id,
        DROP COLUMN IF EXISTS seller_payout_inr,
        DROP COLUMN IF EXISTS platform_fee_inr,
        DROP COLUMN IF EXISTS gross_amount_inr
    """)
    op.execute("""
        ALTER TABLE software_purchases 
        DROP CONSTRAINT IF EXISTS fk_software_purchases_payout_approved_by_user_id_users
    """)
