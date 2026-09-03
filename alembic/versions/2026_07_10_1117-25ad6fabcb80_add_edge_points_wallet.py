"""add_edge_points_wallet

Revision ID: 25ad6fabcb80
Revises: 03a933a2aa64
Create Date: 2026-07-10 11:17:47.268463

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '25ad6fabcb80'
down_revision: Union[str, Sequence[str], None] = '03a933a2aa64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helpers — guard every operation so the migration is idempotent
# ---------------------------------------------------------------------------

def _column_exists(table: str, column: str) -> bool:
    result = op.get_bind().execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column}).fetchone()
    return result is not None


def _table_exists(table: str) -> bool:
    result = op.get_bind().execute(sa.text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = :t"
    ), {"t": table}).fetchone()
    return result is not None


# ---------------------------------------------------------------------------
# upgrade — Edge Points schema only
# ---------------------------------------------------------------------------

def upgrade() -> None:
    """Add edge_points_redemptions table and edge_points column on users."""

    # 1. Create edge_points_redemptions table (new — always safe to create)
    if not _table_exists('edge_points_redemptions'):
        op.create_table(
            'edge_points_redemptions',
            sa.Column('user_id', sa.UUID(), nullable=False),
            sa.Column('razorpay_order_id', sa.String(length=128), nullable=False),
            sa.Column('edge_points_redeemed', sa.Integer(), nullable=False),
            sa.Column(
                'status',
                sa.Enum('PENDING', 'COMPLETED', 'FAILED', name='redemption_status_enum'),
                nullable=False,
            ),
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ['user_id'], ['users.id'],
                name=op.f('fk_edge_points_redemptions_user_id_users'),
                ondelete='CASCADE',
            ),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_edge_points_redemptions')),
        )
        op.create_index(
            op.f('ix_edge_points_redemptions_razorpay_order_id'),
            'edge_points_redemptions',
            ['razorpay_order_id'],
            unique=True,
        )

    # 2. Add edge_points balance column to users (new)
    if not _column_exists('users', 'edge_points'):
        op.add_column(
            'users',
            sa.Column('edge_points', sa.Integer(), nullable=False, server_default='0'),
        )


# ---------------------------------------------------------------------------
# downgrade — reverse Edge Points schema only
# ---------------------------------------------------------------------------

def downgrade() -> None:
    """Remove edge_points_redemptions table and edge_points column from users."""

    if _column_exists('users', 'edge_points'):
        op.drop_column('users', 'edge_points')

    op.execute('DROP INDEX IF EXISTS ix_edge_points_redemptions_razorpay_order_id')
    op.execute('DROP TABLE IF EXISTS edge_points_redemptions')
