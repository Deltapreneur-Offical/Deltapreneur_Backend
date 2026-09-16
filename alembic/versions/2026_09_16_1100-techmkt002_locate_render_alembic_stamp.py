"""Locate Render's leftover Alembic stamp ``techmkt002``.

Revision ID: techmkt002
Revises: techmkt001
Create Date: 2026-09-16 11:00:00.000000

Render's ``alembic_version`` may contain ``techmkt002`` from a prior deploy,
but that revision file was missing from this repository. ``alembic upgrade
head`` then fails with ``Can't locate revision identified by 'techmkt002'``
before the API starts.

This file is a locator only:
- it does not create, alter, or drop any tables/columns
- databases already at ``techmkt001`` just stamp this no-op
- databases already stamped ``techmkt002`` can resolve the id and stay put
"""

from typing import Sequence, Union


revision: str = "techmkt002"
down_revision: Union[str, Sequence[str], None] = "techmkt001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    return


def downgrade() -> None:
    return
