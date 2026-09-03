"""Guard rails for domain auction bidding when listing verification is pending."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.repository.domain_listing_repository import DomainListingRepository
from app.repository.domain_repository import DomainRepository

_VERIFICATION_MESSAGE = (
    "Bidding is blocked until the domain is verified by the owner."
)


async def ensure_domain_verified_for_auction(
    session: AsyncSession,
    domain_id: uuid.UUID,
) -> None:
    """Raise when domain listing verification is required but not complete."""
    if not settings.REQUIRE_DOMAIN_VERIFICATION_BEFORE_PURCHASE:
        return

    listing_repo = DomainListingRepository(session)
    listing = await listing_repo.get_by_id(domain_id)
    if listing is not None:
        if not listing.verified:
            raise AppException(_VERIFICATION_MESSAGE, status_code=400)
        return

    domain_repo = DomainRepository(session)
    domain = await domain_repo.get_by_id_alive(domain_id)
    if domain is not None and not domain.is_verified:
        raise AppException(_VERIFICATION_MESSAGE, status_code=400)
