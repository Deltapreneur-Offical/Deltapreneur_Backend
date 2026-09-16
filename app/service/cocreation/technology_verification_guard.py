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
_REJECTED_MESSAGE = "This technology listing was rejected and cannot be purchased."


def assert_technology_purchasable(software) -> None:
    if software is None:
        raise AppException("Software listing not found.", status_code=404)
    if getattr(software, "rejected", False) is True:
        raise AppException(_REJECTED_MESSAGE, status_code=400)
    if settings.REQUIRE_TECHNOLOGY_VERIFICATION_BEFORE_PURCHASE and not software.verified:
        raise AppException(_VERIFICATION_MESSAGE, status_code=400)


async def ensure_technology_verified(
    session: AsyncSession,
    software_id: uuid.UUID,
) -> None:
    repo = SoftwareRepository(session)
    software = await repo.get_by_id(software_id)
    assert_technology_purchasable(software)
