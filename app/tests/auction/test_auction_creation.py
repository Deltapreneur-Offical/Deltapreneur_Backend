"""
Auction creation + active-listing HTTP tests.

Covers:
- POST /api/v1/auction/domain/{domain_id}  (happy path)
- 409 when a second auction is created for the same domain while one is live
- GET /api/v1/auction/active
- GET /api/v1/auction/{auction_id}
- GET /api/v1/auction/domain/{domain_id}
- Validation: negative / zero price → 422
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.entity.auction.auction_entity import Auction
from app.tests.auction.conftest import CREATION_FEE_JSON
from app.tests.auction.domain_test_util import ensure_domain_owned
from app.utils.enums import AuctionStatus

pytestmark = pytest.mark.asyncio

D101 = uuid.UUID("00000000-0000-4000-8000-000000000101")
D001 = uuid.UUID("00000000-0000-4000-8000-000000000001")


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


async def test_create_auction_returns_201_and_persists(
    client_factory, db_session, seller, test_sessionmaker,
):
    await ensure_domain_owned(
        test_sessionmaker, seller.id, domain_id=D101, domain_name="persist-101.test",
    )
    async with await client_factory(current_user=seller) as client:
        resp = await client.post(
            f"/api/v1/auction/domain/{D101}",
            json={
                "domain_id": str(D101),
                "min_bid_price": "500.00",
                "duration": "ONE_HOUR",
                **CREATION_FEE_JSON,
            },
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["domain_id"] == str(D101)
    assert body["status"] == AuctionStatus.DRAFT.value
    assert Decimal(body["min_bid_price"]) == Decimal("500.00")
    assert body["total_bids"] == 0
    assert body["current_highest_bid"] is None
    assert uuid.UUID(body["created_by"]) == seller.id

    row = (
        await db_session.execute(select(Auction).where(Auction.domain_id == D101))
    ).scalar_one()
    assert row.status == AuctionStatus.DRAFT
    assert row.end_time > row.start_time
    assert row.end_time == row.original_end_time


# --------------------------------------------------------------------------- #
# Listings                                                                    #
# --------------------------------------------------------------------------- #


async def test_active_auctions_returns_only_live_status(
    client_factory, auction_factory, seller
):
    d1 = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
    d2 = uuid.UUID("00000000-0000-4000-8000-0000000000a2")
    d3 = uuid.UUID("00000000-0000-4000-8000-0000000000a3")
    await auction_factory(created_by=seller.id, domain_id=d1, status=AuctionStatus.ACTIVE)
    await auction_factory(created_by=seller.id, domain_id=d2, status=AuctionStatus.UNSOLD)
    await auction_factory(created_by=seller.id, domain_id=d3, status=AuctionStatus.COMPLETED)

    async with await client_factory(current_user=seller) as client:
        resp = await client.get("/api/v1/auction/active")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["domainId"] == str(d1)


async def test_get_auction_by_id_returns_200(client_factory, auction_factory, seller):
    d_auction = uuid.UUID("00000000-0000-4000-8000-000000000042")
    auction = await auction_factory(created_by=seller.id, domain_id=d_auction)

    async with await client_factory(current_user=seller) as client:
        resp = await client.get(f"/api/v1/auction/{auction.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["auction"]["id"] == str(auction.id)


async def test_get_auction_by_id_unknown_returns_404(client_factory, seller):
    async with await client_factory(current_user=seller) as client:
        resp = await client.get(f"/api/v1/auction/{uuid.uuid4()}")

    assert resp.status_code == 404


async def test_get_auction_by_domain_returns_latest(client_factory, auction_factory, seller):
    d7 = uuid.UUID("00000000-0000-4000-8000-000000000007")
    await auction_factory(created_by=seller.id, domain_id=d7, status=AuctionStatus.UNSOLD)
    newest = await auction_factory(
        created_by=seller.id, domain_id=d7, status=AuctionStatus.ACTIVE,
    )

    async with await client_factory(current_user=seller) as client:
        resp = await client.get(f"/api/v1/auction/domain/{d7}")

    assert resp.status_code == 200
    assert resp.json()["id"] == str(newest.id)


# --------------------------------------------------------------------------- #
# Validation                                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "payload",
    [
        {"domain_id": str(D001), "min_bid_price": "0", "duration": "ONE_HOUR"},
        {"domain_id": str(D001), "min_bid_price": "-10.00", "duration": "ONE_HOUR"},
        {"domain_id": str(D001), "min_bid_price": "10.005", "duration": "ONE_HOUR"},
        {"domain_id": str(D001), "min_bid_price": "100.00", "duration": "INVALID"},
    ],
)
async def test_create_auction_rejects_invalid_payloads(
    client_factory, seller, test_sessionmaker, payload,
):
    await ensure_domain_owned(
        test_sessionmaker, seller.id, domain_id=D001, domain_name="validation-001.test",
    )
    async with await client_factory(current_user=seller) as client:
        resp = await client.post(
            f"/api/v1/auction/domain/{D001}",
            json=payload,
        )
    assert resp.status_code == 422
