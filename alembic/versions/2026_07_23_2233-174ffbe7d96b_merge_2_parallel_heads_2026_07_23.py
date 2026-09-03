"""Merge 2 parallel heads (2026-07-23)."""

from alembic import op
import sqlalchemy as sa

revision = "174ffbe7d96b"
down_revision = ("va_20260718_1700", "c5d6e7f8a9b0")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
