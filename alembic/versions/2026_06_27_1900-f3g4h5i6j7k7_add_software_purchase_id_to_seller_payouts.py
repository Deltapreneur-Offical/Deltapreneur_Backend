"""Add software_purchase_id to seller_payouts table.

Revision ID: f3g4h5i6j7k7
Revises: 27f404062b15
Create Date: 2026-06-27 19:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f3g4h5i6j7k7"
down_revision: Union[str, None] = "27f404062b15"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE seller_payouts 
        ADD COLUMN IF NOT EXISTS software_purchase_id UUID
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint 
                WHERE conname = 'fk_seller_payouts_software_purchase_id_software_purchases'
            ) THEN
                ALTER TABLE seller_payouts 
                ADD CONSTRAINT fk_seller_payouts_software_purchase_id_software_purchases 
                FOREIGN KEY (software_purchase_id) REFERENCES software_purchases(id) ON DELETE CASCADE;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE seller_payouts 
        DROP CONSTRAINT IF EXISTS fk_seller_payouts_software_purchase_id_software_purchases,
        DROP COLUMN IF EXISTS software_purchase_id
    """)
