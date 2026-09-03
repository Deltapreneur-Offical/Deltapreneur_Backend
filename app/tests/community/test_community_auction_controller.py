import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user
from app.main import app
from app.service.community.community_auction_service import CommunityAuctionService


client = TestClient(app)


def _fake_user(user_id=None):
    from app.entity.user.user_role import UserRole
    return SimpleNamespace(
        id=user_id or uuid.uuid4(),
        email="test@example.com",
        firstname="Test",
        lastname="User",
        role=UserRole.USER,
        is_deleted=False,
        active=True,
    )


def _fake_auction(
    *,
    auction_id=None,
    community_id=None,
    created_by=None,
    status="PAYMENT_PENDING",
):
    now = datetime.now(timezone.utc)

    return SimpleNamespace(
        id=auction_id or uuid.uuid4(),
        community_id=community_id or uuid.uuid4(),
        created_by=created_by or uuid.uuid4(),
        status=status,
        duration="SEVEN_DAYS",
        min_bid_price=Decimal("500.00"),
        current_highest_bid=None,
        total_bids=0,
        current_winner_id=None,
        start_time=None,
        end_time=None,
        original_end_time=None,
        listing_fee_order_id=None,
        listing_fee_payment_id=None,
        listing_fee_paid=False,
        auction_title="FastAPI Developer Available",
        auction_skills="Python, FastAPI, PostgreSQL",
        work_type="FREELANCE",
        expected_rate="₹500 per hour",
        available_from=None,
        additional_info="Available for backend work",
        created_at=now,
        updated_at=now,
    )


def _fake_bid(
    *,
    bid_id=None,
    auction_id=None,
    bidder_id=None,
    amount=Decimal("600.00"),
):
    now = datetime.now(timezone.utc)

    return SimpleNamespace(
        id=bid_id or uuid.uuid4(),
        auction_id=auction_id or uuid.uuid4(),
        bidder_id=bidder_id or uuid.uuid4(),
        bidder_name="Bidder User",
        amount=amount,
        bid_time=now,
        winning_bid=True,
        created_at=now,
        updated_at=now,
    )


def _login_as(user):
    app.dependency_overrides[get_current_user] = lambda: user


def _clear_login():
    app.dependency_overrides.clear()


def test_community_auction_module_connected():
    response = client.get("/api/v1/community-auctions/test")

    assert response.status_code == 200

    body = response.json()

    assert body["success"] is True
    assert body["message"] == "Creator auction module is connected successfully"
    assert body["data"]["module"] == "community-auction"
    assert body["data"]["status"] == "ready"


def test_get_all_community_auctions_success():
    auction = _fake_auction()

    with patch(
        "app.service.community.community_auction_service.CommunityAuctionRepository.find_all",
        return_value=[auction],
    ):
        response = client.get("/api/v1/community-auctions/all")

    assert response.status_code == 200

    body = response.json()

    assert body["success"] is True
    assert body["message"] == "Creator auctions fetched successfully"
    assert len(body["data"]) == 1
    assert body["data"][0]["auction_title"] == "FastAPI Developer Available"


def test_get_my_community_auctions_success():
    user = _fake_user()
    auction = _fake_auction(created_by=user.id)

    _login_as(user)

    try:
        with patch(
            "app.service.community.community_auction_service.CommunityAuctionService.get_my_auctions",
            return_value=[CommunityAuctionService._to_response(auction)],
        ):
            response = client.get("/api/v1/community-auctions/my")

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "My community auctions fetched successfully"
        assert len(body["data"]) == 1
        assert body["data"][0]["created_by"] == str(user.id)

    finally:
        _clear_login()


def test_get_community_auction_by_id_success():
    auction_id = uuid.uuid4()
    auction = _fake_auction(auction_id=auction_id)

    with patch(
        "app.service.community.community_auction_service.CommunityAuctionRepository.find_by_id",
        return_value=auction,
    ):
        response = client.get(f"/api/v1/community-auctions/{auction_id}")

    assert response.status_code == 200

    body = response.json()

    assert body["success"] is True
    assert body["message"] == "Creator auction fetched successfully"
    assert body["data"]["id"] == str(auction_id)


def test_get_missing_community_auction_returns_404():
    auction_id = uuid.uuid4()

    with patch(
        "app.service.community.community_auction_service.CommunityAuctionRepository.find_by_id",
        return_value=None,
    ):
        response = client.get(f"/api/v1/community-auctions/{auction_id}")

    assert response.status_code == 404


def test_activate_community_auction_success():
    user = _fake_user()
    auction_id = uuid.uuid4()
    auction = _fake_auction(
        auction_id=auction_id,
        created_by=user.id,
        status="PAYMENT_PENDING",
    )

    _login_as(user)

    try:
        def save_side_effect(**kwargs):
            return kwargs["auction"]

        with patch(
            "app.service.community.community_auction_service.CommunityAuctionRepository.find_by_id",
            return_value=auction,
        ), patch(
            "app.service.community.community_auction_service.CommunityAuctionRepository.save",
            side_effect=save_side_effect,
        ), patch(
            "app.service.community.community_auction_service.NotificationService.notify",
        ):
            response = client.put(
                f"/api/v1/community-auctions/{auction_id}/activate"
            )

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "Creator auction activated successfully"
        assert body["data"]["status"] == "ACTIVE"
        assert body["data"]["listing_fee_paid"] is True

    finally:
        _clear_login()


def test_place_community_auction_bid_success():
    owner_id = uuid.uuid4()
    bidder = _fake_user()
    auction_id = uuid.uuid4()

    _login_as(bidder)

    try:
        with patch(
            "app.controller.community.community_auction_controller.CommunityAuctionService.place_bid",
            return_value={"amount": 500.0, "winning_bid": True},
        ):
            response = client.post(
                f"/api/v1/community-auctions/{auction_id}/bids",
                json={
                    "amount": 500,
                    "razorpayOrderId": "order_test_bid",
                    "razorpayPaymentId": "pay_test_bid",
                    "razorpaySignature": "sig_test_bid",
                },
            )

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "Creator auction bid placed successfully"
        assert body["data"]["amount"] == 500.0
        assert body["data"]["winning_bid"] is True

    finally:
        _clear_login()


def test_get_community_auction_bids_success():
    auction_id = uuid.uuid4()
    auction = _fake_auction(auction_id=auction_id)
    bid = _fake_bid(auction_id=auction_id)

    with patch(
        "app.service.community.community_auction_service.CommunityAuctionRepository.find_by_id",
        return_value=auction,
    ), patch(
        "app.service.community.community_auction_service.CommunityAuctionBidRepository.find_by_auction_id",
        return_value=[bid],
    ):
        response = client.get(f"/api/v1/community-auctions/{auction_id}/bids")

    assert response.status_code == 200

    body = response.json()

    assert body["success"] is True
    assert body["message"] == "Creator auction bids fetched successfully"
    assert len(body["data"]) == 1
    assert body["data"][0]["winning_bid"] is True


def test_close_active_community_auction_with_no_bids_success():
    user = _fake_user()
    auction_id = uuid.uuid4()
    community_id = uuid.uuid4()
    auction = _fake_auction(
        auction_id=auction_id,
        community_id=community_id,
        created_by=user.id,
        status="ACTIVE",
    )
    community = SimpleNamespace(id=community_id, app_user_id=user.id)

    _login_as(user)

    try:
        def save_side_effect(**kwargs):
            return kwargs["auction"]

        with patch(
            "app.service.community.community_auction_service.CommunityAuctionRepository.find_by_id",
            return_value=auction,
        ), patch(
            "app.service.community.community_auction_service.CommunityRepository.find_by_id",
            return_value=community,
        ), patch(
            "app.service.community.community_auction_service.CommunityAuctionRepository.save",
            side_effect=save_side_effect,
        ), patch(
            "app.service.community.community_auction_service.CommunityAuctionService._broadcast_auction_event",
        ):
            response = client.post(f"/api/v1/creator-auction/{auction_id}/close")

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["message"] == "Auction closed"
        assert body["data"]["status"] == "CLOSED"
        assert auction.status == "CLOSED"

    finally:
        _clear_login()


def test_close_active_community_auction_with_bids_returns_400():
    user = _fake_user()
    auction_id = uuid.uuid4()
    community_id = uuid.uuid4()
    auction = _fake_auction(
        auction_id=auction_id,
        community_id=community_id,
        created_by=user.id,
        status="ACTIVE",
    )
    auction.total_bids = 2
    community = SimpleNamespace(id=community_id, app_user_id=user.id)

    _login_as(user)

    try:
        with patch(
            "app.service.community.community_auction_service.CommunityAuctionRepository.find_by_id",
            return_value=auction,
        ), patch(
            "app.service.community.community_auction_service.CommunityRepository.find_by_id",
            return_value=community,
        ):
            response = client.post(f"/api/v1/creator-auction/{auction_id}/close")

        assert response.status_code == 400
        body = response.json()
        assert body["message"] == "Cannot close an auction that has active bids"

    finally:
        _clear_login()
