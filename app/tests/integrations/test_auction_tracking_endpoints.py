"""Mocked tests for Your Auctions / Your Bids endpoints — no database."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.auction_tracking import bidder_tracking_fields
from app.utils.enums import AuctionStatus


def test_bidder_tracking_fields_leading_and_winner():
    user_id = uuid.uuid4()
    leading = bidder_tracking_fields(
        user_id=user_id,
        user_highest_bid=1000.0,
        current_highest_bid=1000.0,
        current_winner_id=None,
        status=AuctionStatus.ACTIVE,
    )
    assert leading["isLeading"] is True
    assert leading["isWinner"] is False
    assert leading["paymentPending"] is False

    winner = bidder_tracking_fields(
        user_id=user_id,
        user_highest_bid=2500.0,
        current_highest_bid=2500.0,
        current_winner_id=user_id,
        status=AuctionStatus.PAYMENT_PENDING,
    )
    assert winner["isWinner"] is True
    assert winner["paymentPending"] is True
    assert winner["trackingRole"] == "bidder"


@pytest.mark.asyncio
async def test_domain_list_my_auctions_marks_seller():
    from app.service.auction.auction_service import AuctionService

    user = SimpleNamespace(id=uuid.uuid4())
    auction = SimpleNamespace(
        id=uuid.uuid4(),
        domain_id=uuid.uuid4(),
        status=AuctionStatus.ACTIVE,
        current_highest_bid=0,
        current_winner_id=None,
    )
    service = AuctionService(session=MagicMock())
    service._repo = SimpleNamespace(
        list_by_created_by=AsyncMock(return_value=[auction]),
    )
    service._listing_repo = SimpleNamespace(
        get_by_ids=AsyncMock(return_value=[]),
    )

    with patch(
        "app.model.auction.auction_mapper.build_public_auction_item",
        return_value={"id": str(auction.id), "status": "ACTIVE"},
    ):
        items = await service.list_my_auctions(user)

    assert len(items) == 1
    assert items[0]["auctionType"] == "DOMAIN"
    assert items[0]["trackingRole"] == "seller"


@pytest.mark.asyncio
async def test_domain_list_my_bids_marks_bidder_summary():
    from app.service.auction.auction_service import AuctionService

    user = SimpleNamespace(id=uuid.uuid4())
    auction_id = uuid.uuid4()
    auction = SimpleNamespace(
        id=auction_id,
        domain_id=uuid.uuid4(),
        status=AuctionStatus.ACTIVE,
        current_highest_bid=5000.0,
        current_winner_id=None,
    )
    bid = SimpleNamespace(auction_id=auction_id, amount=5000.0)

    service = AuctionService(session=MagicMock())
    service._repo = SimpleNamespace(
        list_by_ids=AsyncMock(return_value=[auction]),
    )
    service._listing_repo = SimpleNamespace(
        get_by_ids=AsyncMock(return_value=[]),
    )

    with patch(
        "app.repository.bid_repository.BidRepository.list_by_bidder_id",
        new=AsyncMock(return_value=[bid]),
    ), patch(
        "app.model.auction.auction_mapper.build_public_auction_item",
        return_value={"id": str(auction_id), "status": "ACTIVE", "currentHighestBid": 5000},
    ):
        items = await service.list_my_bids(user)

    assert len(items) == 1
    assert items[0]["auctionType"] == "DOMAIN"
    assert items[0]["userHighestBid"] == 5000.0
    assert items[0]["isLeading"] is True
    assert items[0]["trackingRole"] == "bidder"


@pytest.mark.asyncio
async def test_software_list_my_bids_empty():
    from app.service.cocreation.software_auction_service import SoftwareAuctionService

    user = SimpleNamespace(id=uuid.uuid4())
    service = SoftwareAuctionService(session=MagicMock())
    service._bids = SimpleNamespace(list_by_bidder_id=AsyncMock(return_value=[]))
    items = await service.list_my_bids(user)
    assert items == []


def test_creator_get_my_bids_aggregates_highest():
    from app.service.community.community_auction_service import CommunityAuctionService

    user = SimpleNamespace(id=uuid.uuid4())
    auction_id = uuid.uuid4()
    auction = SimpleNamespace(
        id=auction_id,
        current_highest_bid=300.0,
        current_winner_id=None,
        status=SimpleNamespace(value="ACTIVE"),
    )
    # status as enum-like with value for tracking helper
    auction.status = AuctionStatus.ACTIVE

    bids = [
        SimpleNamespace(auction_id=auction_id, amount=200.0),
        SimpleNamespace(auction_id=auction_id, amount=300.0),
    ]

    with patch(
        "app.repository.community_auction_bid_repository.CommunityAuctionBidRepository.find_by_bidder_id",
        return_value=bids,
    ), patch(
        "app.repository.community_auction_repository.CommunityAuctionRepository.find_by_id",
        return_value=auction,
    ), patch.object(
        CommunityAuctionService,
        "_to_response",
        return_value={"id": str(auction_id), "status": "ACTIVE"},
    ), patch.object(
        CommunityAuctionService,
        "_enrich_auction_response",
        side_effect=lambda db, payload, a: payload,
    ):
        items = CommunityAuctionService.get_my_bids(db=MagicMock(), current_user=user)

    assert len(items) == 1
    assert items[0]["userHighestBid"] == 300.0
    assert items[0]["isLeading"] is True
    assert items[0]["auctionType"] == "CREATOR"
