"""Add lookup indexes for listing views and homepage featured cards.

Revision ID: perf_listing_indexes_001
Revises: tech_access_email_status_001
Create Date: 2026-09-12 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "perf_listing_indexes_001"
down_revision: Union[str, Sequence[str], None] = "tech_access_email_status_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEXES = (
    (
        "ix_domain_listing_views_listing_viewer",
        "domain_listing_views",
        ["domain_listing_id", "viewer_id"],
    ),
    (
        "ix_domain_listings_featured_public",
        "domain_listings",
        ["featured", "is_deleted", "taken_down", "status", "domain_status"],
    ),
)


def _index_names(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in set(inspector.get_table_names()):
        return set()
    return {idx["name"] for idx in inspector.get_indexes(table)}


def upgrade() -> None:
    for name, table, columns in INDEXES:
        if name in _index_names(table):
            continue
        if table not in set(sa.inspect(op.get_bind()).get_table_names()):
            continue
        op.create_index(name, table, columns, unique=False)


def downgrade() -> None:
    for name, table, _columns in reversed(INDEXES):
        if name in _index_names(table):
            op.drop_index(name, table_name=table)
