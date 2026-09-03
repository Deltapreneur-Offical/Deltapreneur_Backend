"""create profile views table

Revision ID: b1d2c3e4f5a6
Revises: a4606a3fab70
Create Date: 2026-05-14 11:42:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1d2c3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'a4606a3fab70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'profile_views',
        sa.Column('profile_id', sa.UUID(), nullable=False),
        sa.Column('viewer_id', sa.UUID(), nullable=True),
        sa.Column('viewer_industry', sa.String(length=100), nullable=True),
        sa.Column('viewer_role', sa.String(length=100), nullable=True),
        sa.Column('viewed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ['viewer_id'],
            ['users.id'],
            name=op.f('fk_profile_views_viewer_id_users')
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_profile_views'))
    )
    op.create_index(
        'idx_profile_views_profile_id',
        'profile_views',
        ['profile_id'],
        unique=False
    )
    op.create_index(
        'idx_profile_views_viewed_at',
        'profile_views',
        ['viewed_at'],
        unique=False
    )
    op.create_index(
        'idx_profile_views_viewer_id',
        'profile_views',
        ['viewer_id'],
        unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'idx_profile_views_viewer_id',
        table_name='profile_views'
    )
    op.drop_index(
        'idx_profile_views_viewed_at',
        table_name='profile_views'
    )
    op.drop_index(
        'idx_profile_views_profile_id',
        table_name='profile_views'
    )
    op.drop_table('profile_views')
