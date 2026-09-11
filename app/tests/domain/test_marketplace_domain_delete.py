from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import AppException
from app.service.domain.marketplace_domain_service import MarketplaceDomainService


class FakeSession:
    def __init__(self):
        self.committed = False

    async def commit(self):
        self.committed = True


class FakeListingRepo:
    def __init__(self, listing):
        self.listing = listing
        self.saved = None

    async def get_by_id(self, listing_id):
        if self.listing is None or self.listing.id != listing_id:
            return None
        return self.listing

    async def save(self, listing):
        self.saved = listing
        return listing


def _service(listing):
    service = MarketplaceDomainService.__new__(MarketplaceDomainService)
    service._session = FakeSession()
    service._repo = FakeListingRepo(listing)
    return service


def _listing(*, owner_id, is_deleted=False):
    return SimpleNamespace(
        id=uuid4(),
        listed_by_user_id=owner_id,
        is_deleted=is_deleted,
        deleted_at=None,
        deleted_by=None,
        updated_at=None,
    )


@pytest.mark.asyncio
async def test_delete_listing_allows_owner():
    owner_id = uuid4()
    listing = _listing(owner_id=owner_id)
    actor = SimpleNamespace(id=owner_id)
    service = _service(listing)

    await service.delete_listing(listing.id, actor=actor)

    assert listing.is_deleted is True
    assert listing.deleted_by == actor.id
    assert service._repo.saved is listing
    assert service._session.committed is True


@pytest.mark.asyncio
async def test_delete_listing_rejects_non_owner():
    listing = _listing(owner_id=uuid4())
    actor = SimpleNamespace(id=uuid4())
    service = _service(listing)

    with pytest.raises(AppException) as exc:
        await service.delete_listing(listing.id, actor=actor)

    assert exc.value.status_code == 403
    assert listing.is_deleted is False
    assert service._repo.saved is None
    assert service._session.committed is False


@pytest.mark.asyncio
async def test_delete_listing_rejects_already_deleted():
    owner_id = uuid4()
    listing = _listing(owner_id=owner_id, is_deleted=True)
    actor = SimpleNamespace(id=owner_id)
    service = _service(listing)

    with pytest.raises(AppException) as exc:
        await service.delete_listing(listing.id, actor=actor)

    assert exc.value.status_code == 404
    assert service._session.committed is False
