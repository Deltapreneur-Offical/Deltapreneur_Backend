"""add_creator_profile_new_fields

Revision ID: 026e30dcf1fd
Revises: b1c2d3e4f5a6
Create Date: 2026-06-26 16:35:10.227090

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '026e30dcf1fd'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('community', sa.Column('introduction_video_link', sa.String(1000), nullable=True))
    op.add_column('community', sa.Column('resume_drive_link', sa.String(1000), nullable=True))
    op.add_column('community', sa.Column('portfolio_website_link', sa.String(1000), nullable=True))
    op.add_column('community', sa.Column('preferred_work_type', sa.String(100), nullable=True))
    op.add_column('community', sa.Column('industry_expertise', sa.String(500), nullable=True))
    op.add_column('community', sa.Column('languages_known', sa.String(500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('community', 'languages_known')
    op.drop_column('community', 'industry_expertise')
    op.drop_column('community', 'preferred_work_type')
    op.drop_column('community', 'portfolio_website_link')
    op.drop_column('community', 'resume_drive_link')
    op.drop_column('community', 'introduction_video_link')
