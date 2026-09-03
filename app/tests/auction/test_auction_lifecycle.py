"""
Auction lifecycle tests: DRAFT → ACTIVE → ENDED/UNSOLD/CANCELLED, and re-auction.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.entity.auction.auction_entity import Auction
from app.service.auction.auction_service import AuctionService
from app.tests.auction.conftest import CREATION_FEE_JSON
from app.model.auction.auction_request import ReAuctionRequest
from app.utils.enums import AuctionDuration, AuctionStatus

pytestmark = pytest.mark.asyncio

D88 = uuid.UUID("00000000-0000-4000-8000-000000000088")


# --------------------------------------------------------------------------- #
# Cancel                                                                      #
# --------------------------------------------------------------------------- #


async def test_force_cancel_by_creator_moves_status_to_cancelled(
    client_factory, auction_factory, seller
):
    auction = await auction_factory(created_by=seller.id)

    async with await client_factory(current_user=seller) as client:
        resp = await client.post(
            f"/api/v1/auction/{auction.id}/close",
            params={"force_cancel": "true"},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == AuctionStatus.CANCELLED.value


async def test_force_cancel_by_non_creator_returns_403(
    client_factory, auction_factory, seller, user_factory
):
    auction = await auction_factory(created_by=seller.id)
    other = await user_factory()

    async with await client_factory(current_user=other) as client:
        resp = await client.post(
            f"/api/v1/auction/{auction.id}/close",
            params={"force_cancel": "true"},
        )

    assert resp.status_code == 403


async def test_close_already_terminal_auction_returns_409(
    client_factory, auction_factory, seller
):
    auction = await auction_factory(
        created_by=seller.id, status=AuctionStatus.COMPLETED,
    )
    async with await client_factory(current_user=seller) as client:
        resp = await client.post(f"/api/v1/auction/{auction.id}/close")
    assert resp.status_code == 409


# --------------------------------------------------------------------------- #
# Resolve (no bids → UNSOLD; with bid → PAYMENT_PENDING)                       #
# --------------------------------------------------------------------------- #


async def test_close_with_no_bids_moves_to_unsold(
    client_factory, auction_factory, seller, db_session
):
    auction = await auction_factory(created_by=seller.id)

    async with await client_factory(current_user=seller) as client:
        resp = await client.post(f"/api/v1/auction/{auction.id}/close")

    assert resp.status_code == 200
    assert resp.json()["status"] == AuctionStatus.UNSOLD.value

    row = (await db_session.execute(select(Auction).where(Auction.id == auction.id))).scalar_one()
    assert row.current_winner_id is None


async def test_re_auction_rejected_when_prior_still_live(
    test_sessionmaker, auction_factory, seller
):
    prior = await auction_factory(
        created_by=seller.id, domain_id=D88, status=AuctionStatus.ACTIVE,
    )
    async with test_sessionmaker() as session:
        svc = AuctionService(session)
        with pytest.raises(Exception) as exc_info:
            await svc.re_auction(
                prior.id,
                ReAuctionRequest(
                    domain_id=D88,
                    duration=AuctionDuration.ONE_DAY,
                    **CREATION_FEE_JSON,
                ),
                actor=seller,
            )
    assert "cannot be re-auctioned" in str(exc_info.value).lower() \
        or "already has an active auction" in str(exc_info.value).lower()
