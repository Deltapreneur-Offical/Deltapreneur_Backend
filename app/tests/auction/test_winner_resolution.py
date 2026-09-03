"""
WinnerService + AuctionTimerService resolution tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.entity.auction.auction_entity import Auction
from app.service.auction.winner_service import WinnerService
from app.utils.enums import AuctionStatus

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- #
# Direct WinnerService                                                         #
# --------------------------------------------------------------------------- #


async def test_resolve_auction_with_no_bids_marks_unsold(
    test_sessionmaker, auction_factory, seller, db_session,
):
    auction = await auction_factory(created_by=seller.id)

    async with test_sessionmaker() as session:
        await WinnerService(session).resolve_auction(auction.id)

    row = (await db_session.execute(
        select(Auction).where(Auction.id == auction.id)
    )).scalar_one()
    assert row.status == AuctionStatus.UNSOLD
    assert row.current_winner_id is None


# --------------------------------------------------------------------------- #
# Idempotency                                                                  #
# --------------------------------------------------------------------------- #


async def test_resolve_auction_is_idempotent(
    test_sessionmaker, auction_factory, seller, db_session,
):
    auction = await auction_factory(created_by=seller.id)

    async with test_sessionmaker() as session:
        await WinnerService(session).resolve_auction(auction.id)
    async with test_sessionmaker() as session:
        await WinnerService(session).resolve_auction(auction.id)
    async with test_sessionmaker() as session:
        await WinnerService(session).resolve_auction(auction.id)

    row = (await db_session.execute(
        select(Auction).where(Auction.id == auction.id)
    )).scalar_one()
    assert row.status == AuctionStatus.UNSOLD  # not flipped twice


# --------------------------------------------------------------------------- #
# Timer sweep                                                                  #
# --------------------------------------------------------------------------- #


async def test_timer_sweep_resolves_expired_auctions(
    test_sessionmaker, auction_factory, seller, db_session, monkeypatch,
):
    """
    Drive AuctionTimerService._sweep_once manually with the test sessionmaker
    patched into `app.core.database.AsyncSessionLocal` so the sweep operates
    on the test database.
    """
    from app.service.auction import auction_timer_service as ats_module

    auction = await auction_factory(created_by=seller.id)

    # Force the auction's end_time into the past.
    async with test_sessionmaker() as session:
        await session.execute(
            update(Auction)
            .where(Auction.id == auction.id)
            .values(end_time=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
        await session.commit()

    monkeypatch.setattr(ats_module, "AsyncSessionLocal", test_sessionmaker)
    # WinnerService imports AsyncSessionLocal lazily via session arg only — no
    # patch needed there.

    timer = ats_module.AuctionTimerService()
    await timer._sweep_once()

    row = (await db_session.execute(
        select(Auction).where(Auction.id == auction.id)
    )).scalar_one()
    assert row.status == AuctionStatus.UNSOLD  # no bids → unsold


async def test_timer_sweep_does_not_double_process(
    test_sessionmaker, auction_factory, seller, db_session, monkeypatch,
):
    """Re-running the sweep on already-resolved auctions is a no-op."""
    from app.service.auction import auction_timer_service as ats_module

    auction = await auction_factory(
        created_by=seller.id, status=AuctionStatus.UNSOLD,
    )

    monkeypatch.setattr(ats_module, "AsyncSessionLocal", test_sessionmaker)
    timer = ats_module.AuctionTimerService()

    # Capture row state, run sweep twice, assert nothing changed.
    before = (await db_session.execute(
        select(Auction).where(Auction.id == auction.id)
    )).scalar_one()

    await timer._sweep_once()
    await timer._sweep_once()

    after = (await db_session.execute(
        select(Auction).where(Auction.id == auction.id)
    )).scalar_one()

    assert after.status == before.status == AuctionStatus.UNSOLD
