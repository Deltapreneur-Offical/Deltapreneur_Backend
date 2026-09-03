"""add_pitch_deck_and_youtube_video_to_community

Revision ID: 23ee51a4e8b4
Revises: h9i0j1k2l3m4
Create Date: 2026-07-06 11:44:31.170813

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '23ee51a4e8b4'
down_revision: Union[str, Sequence[str], None] = 'h9i0j1k2l3m4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('community', sa.Column('pitch_deck_link', sa.String(length=1000), nullable=True))
    op.add_column('community', sa.Column('youtube_video_link', sa.String(length=1000), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('community', 'youtube_video_link')
    op.drop_column('community', 'pitch_deck_link')
