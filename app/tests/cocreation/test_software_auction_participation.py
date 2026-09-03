from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import AppException
from app.service.cocreation.software_auction_service import SoftwareAuctionService
from app.utils.cocreation_enums import SoftwareAuctionApprovalStatus
from app.utils.enums import AuctionStatus

BID_FEE_KWARGS = {
    "razorpay_order_id": "order_test_bid",
    "razorpay_payment_id": "pay_test_bid",
    "razorpay_signature": "sig_test_bid",
}


class FakeSession:
    def __init__(self, auction=None):
        self.auction = auction
        self.committed = False

    async def execute(self, stmt):
        # Bid-block / platform_settings lookups must not return the auction row.
        try:
            sql = str(stmt).lower()
        except Exception:
            sql = ""
        if "platform_setting" in sql:
            return SimpleNamespace(scalar_one_or_none=lambda: None)
        return SimpleNamespace(scalar_one_or_none=lambda: self.auction)

    async def commit(self):
        self.committed = True


class FakeAuctions:
    def __init__(self, auction):
        self.auction = auction
        self.saved = None

    async def get_by_id(self, _auction_id, **_kwargs):
        return self.auction

    async def save(self, auction):
        self.saved = auction
        return auction


class FakeBids:
    def __init__(self):
        self.created = []

    async def create(self, bid):
        self.created.append(bid)
        return bid


def _auction():
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        software_id=uuid4(),
        approval_status=SoftwareAuctionApprovalStatus.APPROVED,
        status=AuctionStatus.ACTIVE,
        start_time=now,
        end_time=now + timedelta(days=1),
        min_bid_price=1000.0,
        current_highest_bid=0.0,
        current_winner_id=None,
        total_bids=0,
        featured=False,
    )


def _user():
    return SimpleNamespace(
        id=uuid4(),
        firstname="Bid",
        lastname="User",
        email="bidder@example.test",
    )


def _bid_service(auction, user, *, owner_id=None, verified=True):
    service = SoftwareAuctionService.__new__(SoftwareAuctionService)
    service._session = FakeSession(auction)
    service._auctions = FakeAuctions(auction)
    service._bids = FakeBids()
    service._fee_service = SimpleNamespace(
        verify_bid_fee_payment=AsyncMock(return_value=SimpleNamespace(id=uuid4())),
        consume_bid_fee=AsyncMock(),
    )

    async def get_software(software_id):
        return SimpleNamespace(
            id=software_id,
            listed_by_user_id=owner_id or uuid4(),
            verified=verified,
        )

    service._software = SimpleNamespace(get_by_id=get_software)
    return service


@pytest.mark.asyncio
async def test_place_bid_verifies_and_consumes_bid_fee(monkeypatch):
    auction = _auction()
    bidder = _user()
    service = _bid_service(auction, bidder)

    monkeypatch.setattr(
        "app.service.cocreation.software_auction_service.ensure_technology_verified",
        AsyncMock(),
    )

    response = await service.place_bid(
        auction.id,
        1001.0,
        bidder=bidder,
        **BID_FEE_KWARGS,
    )

    assert response["queued"] is True
    assert auction.current_highest_bid == 1001.0
    assert auction.total_bids == 1
    service._fee_service.verify_bid_fee_payment.assert_awaited_once()
    service._fee_service.consume_bid_fee.assert_awaited_once()


@pytest.mark.asyncio
async def test_software_owner_cannot_bid_own_auction(monkeypatch):
    auction = _auction()
    owner = _user()
    service = _bid_service(auction, owner, owner_id=owner.id)

    monkeypatch.setattr(
        "app.service.cocreation.software_auction_service.ensure_technology_verified",
        AsyncMock(),
    )

    with pytest.raises(AppException) as exc:
        await service.place_bid(
            auction.id,
            1000.0,
            bidder=owner,
            **BID_FEE_KWARGS,
        )

    assert exc.value.status_code == 400
    assert exc.value.message == "You cannot bid on your own listing."


@pytest.mark.asyncio
async def test_software_active_list_returns_frontend_usable_fields(monkeypatch):
    auction = _auction()
    auction.software = SimpleNamespace(
        id=auction.software_id,
        name="AI Ops Tool",
        image_url="https://example.test/tool.png",
        category="AI_ML",
    )

    class FakeAuctionList:
        async def list_active(self):
            return [auction]

    service = SoftwareAuctionService.__new__(SoftwareAuctionService)
    service._auctions = FakeAuctionList()

    monkeypatch.setattr(
        "app.service.cocreation.software_auction_service.software_to_api",
        lambda software: {"id": str(software.id), "name": software.name},
    )

    response = await service.list_active()

    assert len(response) == 1
    assert response[0]["id"] == str(auction.id)
    assert response[0]["softwareId"] == str(auction.software_id)
    assert response[0]["minBidPrice"] == 1000.0
    assert response[0]["currentHighestBid"] == 0.0
    assert response[0]["totalBids"] == 0
    assert response[0]["status"] == "ACTIVE"
    assert response[0]["software"]["name"] == "AI Ops Tool"
