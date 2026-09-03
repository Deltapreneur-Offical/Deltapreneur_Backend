from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user
from app.entity.community.community_auction_status import CommunityAuctionStatus
from app.main import app
from app.service.community.community_auction_service import CommunityAuctionService


client = TestClient(app)


def _fake_user(user_id=None):
    return SimpleNamespace(
        id=user_id or uuid.uuid4(),
        email="user@example.test",
        firstname="Test",
        lastname="User",
        username="testuser",
        oauth_provider=None,
        google_refresh_token=None,
        is_deleted=False,
        active=True,
    )


def _fake_auction(**overrides):
    now = datetime.now(timezone.utc)
    base = SimpleNamespace(
        id=uuid.uuid4(),
        community_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        status=CommunityAuctionStatus.ACTIVE.value,
        duration="SEVEN_DAYS",
        min_bid_price=Decimal("500.00"),
        current_highest_bid=Decimal("20000.00"),
        total_bids=1,
        current_winner_id=uuid.uuid4(),
        start_time=now - timedelta(days=1),
        end_time=now - timedelta(minutes=5),
        original_end_time=now - timedelta(minutes=5),
        listing_fee_order_id=None,
        listing_fee_payment_id=None,
        listing_fee_paid=True,
        winner_payment_order_id=None,
        winner_payment_id=None,
        winner_payment_paid=False,
        auction_title="FastAPI Developer",
        auction_skills="Python",
        work_type="FREELANCE",
        expected_rate="500/hr",
        available_from=None,
        additional_info=None,
        created_at=now,
        updated_at=now,
        is_deleted=False,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _login_as(user):
    app.dependency_overrides[get_current_user] = lambda: user


def test_end_auction_with_bids_sets_ended_and_marks_winner():
    auction = _fake_auction()
    winner = _fake_user(auction.current_winner_id)
    lister = _fake_user()
    community = SimpleNamespace(id=auction.community_id, app_user_id=lister.id)
    top_bid = SimpleNamespace(
        bidder_id=auction.current_winner_id,
        bidder_name="Reyna Gekko",
        winning_bid=False,
        amount=Decimal("20000"),
    )

    db = SimpleNamespace()

    with patch(
        "app.service.community.community_auction_service.CommunityAuctionBidRepository.find_by_auction_id",
        return_value=[top_bid],
    ), patch(
        "app.service.community.community_auction_service.CommunityAuctionRepository.save",
        side_effect=lambda **kwargs: kwargs["auction"],
    ), patch(
        "app.service.community.community_auction_service.CommunityAuctionService._broadcast_auction_event",
    ), patch(
        "app.service.community.community_auction_service.CommunityRepository.find_by_id",
        return_value=community,
    ), patch(
        "app.service.community.community_auction_service.UserRepository.find_by_id",
        side_effect=lambda _db, uid: winner if uid == winner.id else lister,
    ), patch(
        "app.service.community.community_auction_service.NotificationService.notify",
    ):
        result = CommunityAuctionService.end_auction(db, auction)

    assert auction.status == CommunityAuctionStatus.ENDED.value
    assert top_bid.winning_bid is True
    assert result["status"] == CommunityAuctionStatus.ENDED.value
    assert result["currentWinnerName"] == "Test User"


def test_end_auction_without_bids_sets_unsold():
    auction = _fake_auction(
        total_bids=0,
        current_highest_bid=None,
        current_winner_id=None,
    )
    lister = _fake_user()
    community = SimpleNamespace(id=auction.community_id, app_user_id=lister.id)
    db = SimpleNamespace()

    with patch(
        "app.service.community.community_auction_service.CommunityAuctionRepository.save",
        side_effect=lambda **kwargs: kwargs["auction"],
    ), patch(
        "app.service.community.community_auction_service.CommunityAuctionService._broadcast_auction_event",
    ), patch(
        "app.service.community.community_auction_service.CommunityRepository.find_by_id",
        return_value=community,
    ), patch(
        "app.service.community.community_auction_service.UserRepository.find_by_id",
        return_value=lister,
    ), patch(
        "app.service.community.community_auction_service.NotificationService.notify",
    ):
        CommunityAuctionService.end_auction(db, auction)

    assert auction.status == CommunityAuctionStatus.UNSOLD.value


def test_winner_payment_create_order_requires_winner():
    winner = _fake_user()
    auction = _fake_auction(
        status=CommunityAuctionStatus.ENDED.value,
        current_winner_id=winner.id,
    )
    _login_as(winner)

    try:
        with patch(
            "app.service.community.community_auction_service.CommunityAuctionRepository.find_by_id",
            return_value=auction,
        ), patch(
            "app.service.community.community_auction_service.rzp.is_configured",
            return_value=True,
        ), patch(
            "app.service.community.community_auction_service.rzp.create_order",
            return_value={"id": "order_test123"},
        ), patch(
            "app.service.community.community_auction_service.rzp.get_key_id",
            return_value="rzp_test",
        ), patch(
            "app.service.community.community_auction_service.CommunityAuctionRepository.save",
            side_effect=lambda **kwargs: kwargs["auction"],
        ):
            response = client.post(
                f"/api/v1/community-auction/{auction.id}/winner-payment/create-order",
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["orderId"] == "order_test123"
        assert body["amount"] == 20000.0
    finally:
        app.dependency_overrides.clear()
