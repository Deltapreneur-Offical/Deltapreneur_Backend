"""Active auction list stays feature-complete without bid-history loads."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.service.auction.auction_service import AuctionService


@pytest.mark.asyncio
async def test_list_active_enriched_returns_item_and_listing_views():
    listing_id = uuid.uuid4()
    auction = SimpleNamespace(
        id=uuid.uuid4(),
        domain_id=listing_id,
        status=SimpleNamespace(value="ACTIVE"),
        duration=SimpleNamespace(value="SEVEN_DAYS"),
        min_bid_price=1000,
        current_highest_bid=0,
        total_bids=3,
        current_winner_id=None,
        start_time=None,
        end_time=None,
        original_end_time=None,
        created_at=None,
        updated_at=None,
        featured=True,
        domain=None,
    )
    listing = SimpleNamespace(
        id=listing_id,
        domain_name="alpha",
        domain_extension=".com",
        pricing_demand=None,
        logo=None,
        verified=True,
        views=17,
        listed_by=None,
    )

    service = AuctionService(AsyncMock())
    service._repo.get_active_auctions_with_details = AsyncMock(return_value=[auction])
    service._listing_repo.get_by_ids_card = AsyncMock(return_value=[listing])

    items = await service.list_active_enriched(page=1, page_size=50)

    assert len(items) == 1
    assert items[0]["totalBids"] == 3
    assert items[0]["domain"]["views"] == 17
    assert items[0]["domain"]["fullDomain"] == "alpha.com"
    service._listing_repo.get_by_ids_card.assert_awaited_once_with([listing_id])
