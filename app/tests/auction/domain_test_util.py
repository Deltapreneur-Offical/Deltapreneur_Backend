"""Shared helpers for auction tests (domain rows for ownership checks)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.entity.auction.domain_entity import Domain


async def ensure_domain_owned(
    sessionmaker: async_sessionmaker[AsyncSession],
    owner_id: uuid.UUID,
    *,
    domain_id: uuid.UUID | None = None,
    domain_name: str | None = None,
) -> uuid.UUID:
    """Ensure a live Domain row exists for ``owner_id``; idempotent per ``domain_id``."""
    did = domain_id or uuid.uuid4()
    name = (domain_name or f"test-{did.hex[:12]}.local").strip().lower()
    async with sessionmaker() as session:
        existing = await session.get(Domain, did)
        if existing is not None:
            if existing.owner_id != owner_id:
                raise ValueError("domain_id already exists with a different owner")
            if existing.is_deleted:
                existing.is_deleted = False
                existing.deleted_at = None
                existing.deleted_by = None
            if existing.domain_name != name:
                existing.domain_name = name
            await session.commit()
            return did

        session.add(
            Domain(
                id=did,
                owner_id=owner_id,
                domain_name=name,
                description=None,
                is_verified=False,
            )
        )
        await session.commit()
    return did
