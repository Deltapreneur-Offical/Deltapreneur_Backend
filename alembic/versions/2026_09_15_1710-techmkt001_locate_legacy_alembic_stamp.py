"""Locate Render's leftover Alembic stamp ``techmkt001``.

Revision ID: techmkt001
Revises: perf_listing_indexes_001
Create Date: 2026-09-15 17:10:00.000000

Render's ``alembic_version`` still contains ``techmkt001``, but that revision
file is not in this repository. ``alembic upgrade head`` then fails with
``Can't locate revision identified by 'techmkt001'`` before the API starts.

This file is a locator only:
- it does not create, alter, or drop any tables/columns
- databases already at ``perf_listing_indexes_001`` just stamp this no-op
- databases already stamped ``techmkt001`` can resolve the id and stay put
"""

from typing import Sequence, Union


revision: str = "techmkt001"
down_revision: Union[str, Sequence[str], None] = "perf_listing_indexes_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    return


def downgrade() -> None:
    return
