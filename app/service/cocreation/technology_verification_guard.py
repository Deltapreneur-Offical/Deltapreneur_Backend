"""Guard rails for technology listing purchase and auction bidding."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.repository.software_repository import SoftwareRepository

_VERIFICATION_MESSAGE = (
    "This technology listing is not verified yet. "
    "Purchases and bids are blocked until an admin approves it."
)


async def ensure_technology_verified(
    session: AsyncSession,
    software_id: uuid.UUID,
) -> None:
    if not settings.REQUIRE_TECHNOLOGY_VERIFICATION_BEFORE_PURCHASE:
        return

    repo = SoftwareRepository(session)
    software = await repo.get_by_id(software_id)
    if software is None:
        raise AppException("Software listing not found.", status_code=404)
    if not software.verified:
        raise AppException(_VERIFICATION_MESSAGE, status_code=400)
