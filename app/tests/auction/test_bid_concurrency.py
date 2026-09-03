"""Bid rejection must not leave partial rows behind."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import AppException
from app.entity.auction.auction_entity import Auction
from app.entity.auction.bid_entity import Bid
from app.service.auction.bid_service import BidService
from app.tests.auction.conftest import make_place_bid_request

pytestmark = pytest.mark.asyncio


async def test_rejected_bid_does_not_persist(
    test_sessionmaker, auction_factory, seller, user_factory, db_session,
):
    auction = await auction_factory(
        created_by=seller.id, min_bid_price=Decimal("1000.00"),
    )
    bidder = await user_factory()

    async with test_sessionmaker() as session:
        svc = BidService(session)
        with pytest.raises(AppException):
            await svc.place_bid(
                make_place_bid_request(auction.id, Decimal("50.00")),
                bidder=bidder,
            )

    bids = (await db_session.execute(
        select(Bid).where(Bid.auction_id == auction.id)
    )).scalars().all()
    assert bids == []
    row = (await db_session.execute(
        select(Auction).where(Auction.id == auction.id)
    )).scalar_one()
    assert row.total_bids == 0
    assert row.current_highest_bid is None
