from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user
from app.main import app


client = TestClient(app)


def _fake_user(user_id=None):
    return SimpleNamespace(
        id=user_id or uuid.uuid4(),
        email="owner@example.test",
        firstname="Owner",
        lastname="User",
        username="owner",
        oauth_provider=None,
        google_refresh_token=None,
        is_deleted=False,
        active=True,
    )


def test_community_participation_status_marks_owner():
    owner = _fake_user()
    auction_id = uuid.uuid4()
    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        with (
            patch(
                "app.controller.community.community_auction_controller.CommunityAuctionRepository.find_by_id",
                return_value=SimpleNamespace(id=auction_id),
            ),
            patch(
                "app.controller.community.community_auction_controller.is_community_auction_owner_sync",
                return_value=True,
            ),
        ):
            response = client.get(
                f"/api/v1/community-auctions/{auction_id}/participation/status",
            )
        assert response.status_code == 200
        body = response.json()
        data = body.get("data") or body
        assert data["isOwner"] is True
        assert data["canBid"] is False
        assert data["paid"] is True
    finally:
        app.dependency_overrides.clear()


def test_community_participation_create_order_rejects_owner():
    owner = _fake_user()
    auction_id = uuid.uuid4()
    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        with (
            patch(
                "app.controller.community.community_auction_controller.CommunityAuctionRepository.find_by_id",
                return_value=SimpleNamespace(id=auction_id),
            ),
            patch(
                "app.controller.community.community_auction_controller.is_community_auction_owner_sync",
                return_value=True,
            ),
        ):
            response = client.post(
                f"/api/v1/community-auctions/{auction_id}/participation/create-order",
            )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()
