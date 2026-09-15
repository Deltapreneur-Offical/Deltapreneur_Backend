"""Optional page_size on featured_only public lists (homepage). Omit = full featured set."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.service.cocreation.cocreation_service import CocreationService
from app.service.community.community_service import CommunityService
from app.service.domain.marketplace_domain_service import MarketplaceDomainService
from app.service.venture.venture_service import VentureService
from app.repository.community_repository import CommunityRepository


@pytest.mark.asyncio
async def test_domain_featured_omits_limit_when_page_size_missing():
    service = MarketplaceDomainService(MagicMock())
    service._repo.list_homepage_featured = AsyncMock(return_value=[])
    await service.list_public_page(featured_only=True)
    service._repo.list_homepage_featured.assert_awaited_once_with(limit=None)


@pytest.mark.asyncio
async def test_domain_featured_passes_page_size_as_limit():
    service = MarketplaceDomainService(MagicMock())
    service._repo.list_homepage_featured = AsyncMock(return_value=[])
    await service.list_public_page(featured_only=True, page_size=8)
    service._repo.list_homepage_featured.assert_awaited_once_with(limit=8)


@pytest.mark.asyncio
async def test_venture_featured_omits_limit_when_page_size_missing():
    service = VentureService(MagicMock())
    service._repo.list_homepage_featured = AsyncMock(return_value=[])
    await service.list_public_page(featured_only=True, listing_mode=None)
    service._repo.list_homepage_featured.assert_awaited_once_with(
        listing_mode=None,
        limit=None,
    )


@pytest.mark.asyncio
async def test_venture_featured_passes_page_size_as_limit():
    service = VentureService(MagicMock())
    service._repo.list_homepage_featured = AsyncMock(return_value=[])
    await service.list_public_page(featured_only=True, listing_mode=None, page_size=8)
    service._repo.list_homepage_featured.assert_awaited_once_with(
        listing_mode=None,
        limit=8,
    )


@pytest.mark.asyncio
async def test_software_featured_omits_limit_when_page_size_missing():
    service = CocreationService(MagicMock())
    service._repo.list_homepage_featured = AsyncMock(return_value=[])
    await service.list_public_page(featured_only=True)
    service._repo.list_homepage_featured.assert_awaited_once_with(limit=None)


@pytest.mark.asyncio
async def test_software_featured_passes_page_size_as_limit():
    service = CocreationService(MagicMock())
    service._repo.list_homepage_featured = AsyncMock(return_value=[])
    await service.list_public_page(featured_only=True, page_size=8)
    service._repo.list_homepage_featured.assert_awaited_once_with(limit=8)


def test_community_featured_omits_limit_when_page_size_missing(monkeypatch):
    calls = []

    def fake_find_for_listing(db, *, featured_only=False, limit=None):
        calls.append({"featured_only": featured_only, "limit": limit})
        return []

    monkeypatch.setattr(CommunityRepository, "find_for_listing", staticmethod(fake_find_for_listing))
    monkeypatch.setattr(
        "app.service.community.community_service.ProfileViewRepository.bulk_unique_viewer_counts",
        lambda db, ids: {},
    )
    monkeypatch.setattr(
        "app.repository.community_auction_repository.CommunityAuctionRepository.find_by_community_ids",
        lambda db, ids: [],
    )
    CommunityService.get_all_profiles(MagicMock(), featured_only=True)
    assert calls == [{"featured_only": True, "limit": None}]


def test_community_featured_passes_page_size_as_limit(monkeypatch):
    calls = []

    def fake_find_for_listing(db, *, featured_only=False, limit=None):
        calls.append({"featured_only": featured_only, "limit": limit})
        return []

    monkeypatch.setattr(CommunityRepository, "find_for_listing", staticmethod(fake_find_for_listing))
    monkeypatch.setattr(
        "app.service.community.community_service.ProfileViewRepository.bulk_unique_viewer_counts",
        lambda db, ids: {},
    )
    monkeypatch.setattr(
        "app.repository.community_auction_repository.CommunityAuctionRepository.find_by_community_ids",
        lambda db, ids: [],
    )
    CommunityService.get_all_profiles(MagicMock(), featured_only=True, page_size=8)
    assert calls == [{"featured_only": True, "limit": 8}]
