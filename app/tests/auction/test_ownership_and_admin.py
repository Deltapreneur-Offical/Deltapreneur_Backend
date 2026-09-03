"""Ownership checks and admin-only auction routes."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.tests.auction.conftest import CREATION_FEE_JSON
from app.tests.auction.domain_test_util import ensure_domain_owned
from app.utils.enums import AuctionDuration, AuctionStatus

pytestmark = pytest.mark.asyncio

D55 = uuid.UUID("00000000-0000-4000-8000-000000000055")
D90 = uuid.UUID("00000000-0000-4000-8000-000000000090")
D91 = uuid.UUID("00000000-0000-4000-8000-000000000091")


async def test_create_auction_for_domain_not_owned_returns_403(
    client_factory, seller, user_factory, test_sessionmaker,
):
    other = await user_factory()
    await ensure_domain_owned(
        test_sessionmaker, other.id, domain_id=D55, domain_name="other-55.test",
    )
    async with await client_factory(current_user=seller) as client:
        resp = await client.post(
            f"/api/v1/auction/domain/{D55}",
            json={
                "domain_id": str(D55),
                "min_bid_price": "100.00",
                "duration": "ONE_HOUR",
                **CREATION_FEE_JSON,
            },
        )
    assert resp.status_code == 403


async def test_admin_list_all_returns_200(
    client_factory, admin_user, auction_factory, seller,
):
    d1 = uuid.UUID("00000000-0000-4000-8000-0000000000c1")
    await auction_factory(created_by=seller.id, domain_id=d1)
    async with await client_factory(current_user=admin_user) as client:
        resp = await client.get("/api/v1/auction/admin/all")
    assert resp.status_code == 200
    body = resp.json()
    rows = body.get("data") or body.get("items") or []
    assert body.get("count", len(rows)) >= 1
    if rows:
        first = rows[0]
        assert "auction" in first
        assert "bids" in first


async def test_non_admin_list_all_returns_403(
    client_factory, seller, auction_factory,
):
    d1 = uuid.UUID("00000000-0000-4000-8000-0000000000c2")
    await auction_factory(created_by=seller.id, domain_id=d1)
    async with await client_factory(current_user=seller) as client:
        resp = await client.get("/api/v1/auction/admin/all")
    assert resp.status_code == 403


async def test_close_resolve_by_non_owner_returns_403(
    client_factory, auction_factory, seller, user_factory,
):
    auction = await auction_factory(created_by=seller.id)
    other = await user_factory()
    async with await client_factory(current_user=other) as client:
        resp = await client.post(f"/api/v1/auction/{auction.id}/close")
    assert resp.status_code == 403


async def test_force_cancel_by_admin_on_foreign_auction_succeeds(
    client_factory, auction_factory, seller, admin_user,
):
    auction = await auction_factory(created_by=seller.id)
    async with await client_factory(current_user=admin_user) as client:
        resp = await client.post(
            f"/api/v1/auction/{auction.id}/close",
            params={"force_cancel": "true"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == AuctionStatus.CANCELLED.value


async def test_re_auction_non_owner_returns_403(
    client_factory, auction_factory, seller, user_factory,
):
    prior = await auction_factory(
        created_by=seller.id, domain_id=D90, status=AuctionStatus.UNSOLD,
    )
    other = await user_factory()
    async with await client_factory(current_user=other) as client:
        resp = await client.post(
            f"/api/v1/auction/{prior.id}/re-auction",
            json={
                "domain_id": str(D90),
                "duration": "ONE_HOUR",
                "min_bid_price": "150.00",
                **CREATION_FEE_JSON,
            },
        )
    assert resp.status_code == 403


async def test_re_auction_http_happy_path(
    client_factory, auction_factory, seller,
):
    prior = await auction_factory(
        created_by=seller.id, domain_id=D91, status=AuctionStatus.UNSOLD,
    )
    async with await client_factory(current_user=seller) as client:
        resp = await client.post(
            f"/api/v1/auction/{prior.id}/re-auction",
            json={
                "domain_id": str(D91),
                "duration": "ONE_HOUR",
                "min_bid_price": "175.00",
                **CREATION_FEE_JSON,
            },
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["domain_id"] == str(D91)
    assert Decimal(body["min_bid_price"]) == Decimal("175.00")
