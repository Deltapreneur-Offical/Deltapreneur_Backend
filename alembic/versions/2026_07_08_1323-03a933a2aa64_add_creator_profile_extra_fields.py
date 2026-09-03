"""add_creator_profile_extra_fields

Revision ID: 03a933a2aa64
Revises: 23ee51a4e8b4
Create Date: 2026-07-08 13:23:14.754614

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '03a933a2aa64'
down_revision: Union[str, Sequence[str], None] = '23ee51a4e8b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('community', sa.Column('headline', sa.String(length=255), nullable=True))
    op.add_column('community', sa.Column('education', sa.String(length=500), nullable=True))
    op.add_column('community', sa.Column('graduation_year', sa.String(length=10), nullable=True))
    op.add_column('community', sa.Column('experience', sa.String(length=100), nullable=True))
    op.add_column('community', sa.Column('github_profile', sa.String(length=1000), nullable=True))
    op.add_column('community', sa.Column('social_media_profile', sa.String(length=1000), nullable=True))
    op.add_column('community', sa.Column('current_company', sa.String(length=255), nullable=True))
    op.add_column('community', sa.Column('designation', sa.String(length=255), nullable=True))
    op.add_column('community', sa.Column('role_description', sa.Text(), nullable=True))
    op.add_column('community', sa.Column('company_name', sa.String(length=255), nullable=True))
    op.add_column('community', sa.Column('company_website', sa.String(length=1000), nullable=True))
    op.add_column('community', sa.Column('availability', sa.String(length=255), nullable=True))
    op.add_column('community', sa.Column('hiring_for', sa.Text(), nullable=True))
    op.add_column('community', sa.Column('mentorship_topics', sa.Text(), nullable=True))
    op.add_column('community', sa.Column('investment_focus', sa.Text(), nullable=True))
    op.add_column('community', sa.Column('investment_stage', sa.String(length=255), nullable=True))
    op.add_column('community', sa.Column('ticket_size', sa.String(length=255), nullable=True))
    op.add_column('community', sa.Column('startup_stage', sa.String(length=255), nullable=True))
    op.add_column('community', sa.Column('co_founder_needs', sa.Text(), nullable=True))
    op.add_column('community', sa.Column('incubation_programs', sa.Text(), nullable=True))
    op.add_column('community', sa.Column('support_offered', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('community', 'support_offered')
    op.drop_column('community', 'incubation_programs')
    op.drop_column('community', 'co_founder_needs')
    op.drop_column('community', 'startup_stage')
    op.drop_column('community', 'ticket_size')
    op.drop_column('community', 'investment_stage')
    op.drop_column('community', 'investment_focus')
    op.drop_column('community', 'mentorship_topics')
    op.drop_column('community', 'hiring_for')
    op.drop_column('community', 'availability')
    op.drop_column('community', 'company_website')
    op.drop_column('community', 'company_name')
    op.drop_column('community', 'role_description')
    op.drop_column('community', 'designation')
    op.drop_column('community', 'current_company')
    op.drop_column('community', 'social_media_profile')
    op.drop_column('community', 'github_profile')
    op.drop_column('community', 'experience')
    op.drop_column('community', 'graduation_year')
    op.drop_column('community', 'education')
    op.drop_column('community', 'headline')
