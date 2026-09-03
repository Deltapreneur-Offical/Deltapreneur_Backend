from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user
from app.main import app


client = TestClient(app)

CREATION_FEE_ORDER = "order_test_creation_fee"


def _fake_user(user_id=None):
    from app.entity.user.user_role import UserRole
    return SimpleNamespace(
        id=user_id or uuid.uuid4(),
        email="user@example.test",
        firstname="Test",
        lastname="User",
        username="testuser",
        role=UserRole.USER,
        oauth_provider=None,
        google_refresh_token=None,
        is_deleted=False,
        active=True,
    )


def _login_as(user):
    app.dependency_overrides[get_current_user] = lambda: user


def _clear_login():
    app.dependency_overrides.clear()


def test_disruptor_singular_create_endpoint_matches_frontend_contract():
    owner = _fake_user()
    community_id = uuid.uuid4()
    _login_as(owner)

    try:
        def save_auction_side_effect(**kwargs):
            auction = kwargs["auction"]
            auction.id = uuid.uuid4()
            auction.created_at = datetime.now(timezone.utc)
            auction.updated_at = auction.created_at
            return auction

        with patch(
            "app.service.community.community_auction_service.CommunityRepository.find_by_id",
            return_value=SimpleNamespace(id=community_id, app_user_id=owner.id),
        ), patch(
            "app.service.community.community_auction_service.CommunityAuctionRepository.find_by_community_id",
            return_value=None,
        ), patch(
            "app.service.community.community_auction_service.CommunityAuctionRepository.save",
            side_effect=save_auction_side_effect,
        ), patch(
            "app.service.community.community_auction_service.consume_creation_fee_sync",
        ), patch(
            "app.service.community.community_auction_service.NotificationService.notify",
        ):
            response = client.post(
                f"/api/v1/community-auction/?communityId={community_id}",
                json={
                    "duration": "SEVEN_DAYS",
                    "minBidPrice": 500,
                    "auctionTitle": "FastAPI Developer",
                    "auctionSkills": "Python, FastAPI",
                    "workType": "FREELANCE",
                    "expectedRate": "500/hr",
                    "creationFeeOrderId": CREATION_FEE_ORDER,
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["auction"]["communityId"] == str(community_id)
        assert body["auction"]["minBidPrice"] == 500.0
        assert body["auction"]["currentHighestBid"] == 0
        assert body["auction"]["totalBids"] == 0
        assert body["auction"]["status"] == "ACTIVE"
    finally:
        _clear_login()


def test_disruptor_create_rejects_active_auction():
    owner = _fake_user()
    community_id = uuid.uuid4()
    _login_as(owner)

    existing = SimpleNamespace(
        id=uuid.uuid4(),
        community_id=community_id,
        status="ACTIVE",
    )

    try:
        with patch(
            "app.service.community.community_auction_service.CommunityRepository.find_by_id",
            return_value=SimpleNamespace(id=community_id, app_user_id=owner.id),
        ), patch(
            "app.service.community.community_auction_service.CommunityAuctionRepository.find_by_community_id",
            return_value=existing,
        ):
            response = client.post(
                f"/api/v1/community-auction/?communityId={community_id}",
                json={
                    "duration": "ONE_DAY",
                    "minBidPrice": 20000,
                    "auctionTitle": "backend developer",
                    "workType": "OPEN_TO_ALL",
                    "expectedRate": "$10/hr",
                    "availableFrom": "may 2026",
                    "creationFeeOrderId": CREATION_FEE_ORDER,
                },
            )

        assert response.status_code == 409
        body = response.json()
        assert "live auction" in (body.get("error") or body.get("message") or "").lower()
    finally:
        _clear_login()


def test_disruptor_create_reuses_ended_auction_for_new_listing():
    owner = _fake_user()
    community_id = uuid.uuid4()
    _login_as(owner)

    existing = SimpleNamespace(
        id=uuid.uuid4(),
        community_id=community_id,
        status="ENDED",
        created_by=owner.id,
        duration="SEVEN_DAYS",
        min_bid_price=1000,
        current_highest_bid=5000,
        total_bids=3,
        current_winner_id=uuid.uuid4(),
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        original_end_time=datetime.now(timezone.utc),
        listing_fee_order_id="order_old",
        listing_fee_payment_id="pay_old",
        listing_fee_paid=True,
        winner_payment_order_id="worder_old",
        winner_payment_id="wpay_old",
        winner_payment_paid=False,
        auction_title="Old title",
        auction_skills="Old",
        work_type="FREELANCE",
        expected_rate="100/hr",
        available_from=None,
        additional_info=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    try:
        with patch(
            "app.service.community.community_auction_service.CommunityRepository.find_by_id",
            return_value=SimpleNamespace(id=community_id, app_user_id=owner.id),
        ), patch(
            "app.service.community.community_auction_service.CommunityAuctionRepository.find_by_community_id",
            return_value=existing,
        ), patch(
            "app.service.community.community_auction_service.CommunityAuctionBidRepository.find_by_auction_id",
            return_value=[],
        ), patch(
            "app.service.community.community_auction_service.CommunityAuctionRepository.save",
            side_effect=lambda db, auction: auction,
        ), patch(
            "app.service.community.community_auction_service.consume_creation_fee_sync",
        ), patch(
            "app.service.community.community_auction_service.NotificationService.notify",
        ):
            response = client.post(
                f"/api/v1/community-auction/?communityId={community_id}",
                json={
                    "duration": "ONE_DAY",
                    "minBidPrice": 20000,
                    "auctionTitle": "backend developer",
                    "workType": "OPEN_TO_ALL",
                    "expectedRate": "$10/hr",
                    "availableFrom": "may 2026",
                    "creationFeeOrderId": CREATION_FEE_ORDER,
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["auction"]["status"] == "ACTIVE"
        assert body["auction"]["auctionTitle"] == "backend developer"
        assert body["auction"]["minBidPrice"] == 20000.0
        assert existing.status == "ACTIVE"
        assert existing.listing_fee_paid is True
        assert existing.winner_payment_paid is False
    finally:
        _clear_login()


def test_disruptor_meeting_request_rejects_self_as_lister():
    user = _fake_user()
    auction_id = uuid.uuid4()
    community_id = uuid.uuid4()
    scheduled_at = datetime.now(timezone.utc) + timedelta(days=1)
    _login_as(user)

    auction = SimpleNamespace(
        id=auction_id,
        community_id=community_id,
        status="ACTIVE",
        end_time=scheduled_at + timedelta(hours=2),
        created_by=user.id,
    )

    try:
        with patch(
            "app.service.community.meeting_schedule_service.CommunityAuctionRepository.find_by_id",
            return_value=auction,
        ), patch(
            "app.service.community.meeting_schedule_service.CommunityRepository.find_by_id",
            return_value=SimpleNamespace(id=community_id, app_user_id=user.id),
        ):
            response = client.post(
                f"/api/v1/meetings/auction/{auction_id}",
                json={
                    "scheduledAt": scheduled_at.isoformat(),
                    "durationMinutes": 30,
                    "topic": "Self test",
                },
            )

        assert response.status_code == 400
        body = response.json()
        assert "yourself" in (body.get("error") or body.get("message") or "").lower()
    finally:
        _clear_login()


def test_disruptor_meeting_request_endpoint_happy_path():
    requester = _fake_user()
    lister = _fake_user()
    auction_id = uuid.uuid4()
    community_id = uuid.uuid4()
    scheduled_at = datetime.now(timezone.utc) + timedelta(days=1)
    _login_as(requester)

    auction = SimpleNamespace(
        id=auction_id,
        community_id=community_id,
        status="ACTIVE",
        end_time=scheduled_at + timedelta(hours=2),
    )
    bid = SimpleNamespace(
        id=uuid.uuid4(),
        auction_id=auction_id,
        bidder_id=requester.id,
    )

    try:
        with patch(
            "app.service.community.meeting_schedule_service.CommunityAuctionRepository.find_by_id",
            return_value=auction,
        ), patch(
            "app.service.community.meeting_schedule_service.CommunityRepository.find_by_id",
            return_value=SimpleNamespace(id=community_id, app_user_id=lister.id),
        ), patch(
            "app.service.community.meeting_schedule_service.CommunityAuctionBidRepository.find_by_bidder_id",
            return_value=[bid],
        ), patch(
            "app.service.community.meeting_schedule_service.MeetingScheduleRepository.lister_confirmed_overlap",
            return_value=[],
        ), patch(
            "app.service.community.meeting_schedule_service.MeetingScheduleRepository.requester_confirmed_overlap",
            return_value=[],
        ), patch(
            "app.service.community.meeting_schedule_service.MeetingScheduleRepository.save",
        ), patch(
            "app.service.community.meeting_schedule_service.UserRepository.find_by_id",
            return_value=lister,
        ), patch(
            "app.service.community.meeting_schedule_service.NotificationService.notify",
        ):
            response = client.post(
                f"/api/v1/meetings/auction/{auction_id}",
                json={
                    "scheduledAt": scheduled_at.isoformat(),
                    "durationMinutes": 30,
                    "topic": "Project discovery",
                    "message": "Let's discuss the build.",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["meeting"]["auctionId"] == str(auction_id)
        assert body["meeting"]["listerId"] == str(lister.id)
        assert body["meeting"]["requesterId"] == str(requester.id)
        assert body["meeting"]["status"] == "PENDING"
    finally:
        _clear_login()


def test_disruptor_meeting_request_rejects_without_bid():
    requester = _fake_user()
    lister = _fake_user()
    auction_id = uuid.uuid4()
    community_id = uuid.uuid4()
    scheduled_at = datetime.now(timezone.utc) + timedelta(days=1)
    _login_as(requester)

    auction = SimpleNamespace(
        id=auction_id,
        community_id=community_id,
        status="ACTIVE",
        end_time=scheduled_at + timedelta(hours=2),
    )

    try:
        with patch(
            "app.service.community.meeting_schedule_service.CommunityAuctionRepository.find_by_id",
            return_value=auction,
        ), patch(
            "app.service.community.meeting_schedule_service.CommunityRepository.find_by_id",
            return_value=SimpleNamespace(id=community_id, app_user_id=lister.id),
        ), patch(
            "app.service.community.meeting_schedule_service.CommunityAuctionBidRepository.find_by_bidder_id",
            return_value=[],
        ):
            response = client.post(
                f"/api/v1/meetings/auction/{auction_id}",
                json={
                    "scheduledAt": scheduled_at.isoformat(),
                    "durationMinutes": 30,
                    "topic": "Project discovery",
                },
            )

        assert response.status_code == 403
        body = response.json()
        assert "bid" in (body.get("error") or body.get("message") or body.get("detail") or "").lower()
    finally:
        _clear_login()


def test_disruptor_meeting_request_rejects_when_auction_not_live():
    requester = _fake_user()
    lister = _fake_user()
    auction_id = uuid.uuid4()
    community_id = uuid.uuid4()
    scheduled_at = datetime.now(timezone.utc) + timedelta(days=1)
    _login_as(requester)

    auction = SimpleNamespace(
        id=auction_id,
        community_id=community_id,
        status="ENDED",
        end_time=scheduled_at + timedelta(hours=2),
    )

    try:
        with patch(
            "app.service.community.meeting_schedule_service.CommunityAuctionRepository.find_by_id",
            return_value=auction,
        ), patch(
            "app.service.community.meeting_schedule_service.CommunityRepository.find_by_id",
            return_value=SimpleNamespace(id=community_id, app_user_id=lister.id),
        ):
            response = client.post(
                f"/api/v1/meetings/auction/{auction_id}",
                json={
                    "scheduledAt": scheduled_at.isoformat(),
                    "durationMinutes": 30,
                    "topic": "Project discovery",
                },
            )

        assert response.status_code == 400
        body = response.json()
        assert "active" in (body.get("error") or body.get("message") or "").lower()
    finally:
        _clear_login()


def test_community_auction_response_derives_end_time_and_preserves_expected_rate():
    from app.service.community.community_auction_service import CommunityAuctionService

    start = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    auction = SimpleNamespace(
        id=uuid.uuid4(),
        community_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        status="ACTIVE",
        duration="SEVEN_DAYS",
        min_bid_price=500,
        current_highest_bid=0,
        total_bids=0,
        current_winner_id=None,
        start_time=start,
        end_time=None,
        original_end_time=None,
        listing_fee_order_id=None,
        listing_fee_payment_id=None,
        listing_fee_paid=True,
        auction_title="FastAPI Developer",
        auction_skills="Python",
        work_type="FREELANCE",
        expected_rate="500/hr",
        available_from=None,
        additional_info=None,
        created_at=start,
        updated_at=start,
    )

    payload = CommunityAuctionService._to_response(auction)

    assert payload["expectedRate"] == "500/hr"
    assert payload["endTime"] is not None
    assert payload["endTime"].startswith("2026-05-08")
    assert payload["originalEndTime"] == payload["endTime"]
