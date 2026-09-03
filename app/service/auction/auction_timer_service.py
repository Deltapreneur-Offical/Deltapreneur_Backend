"""
AuctionTimerService — APScheduler-driven closure of expired auctions.

Runs on the FastAPI event loop. Every POLL_INTERVAL_SECONDS:

1. Fetch a batch of ACTIVE/EXTENDED auctions whose end_time has elapsed.
2. For each, open a fresh AsyncSession and call WinnerService.resolve_auction.
3. WinnerService takes a row-level lock per auction, so two overlapping
   sweeps cannot double-process the same row.

`max_instances=1` and a process-local `_running` guard provide a second
defense against duplicate work on the same node.

NOTE: For multi-instance deployments, run the scheduler on exactly one node
(e.g. a "worker" replica) or guard with a distributed lock.

APScheduler is an optional dependency — the app boots fine without it; the
scheduler simply will not start and a warning is logged instead.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    _APSCHEDULER_AVAILABLE = True
except ImportError:
    AsyncIOScheduler = None  # type: ignore[assignment,misc]
    IntervalTrigger = None   # type: ignore[assignment,misc]
    _APSCHEDULER_AVAILABLE = False

from app.core.database import AsyncSessionLocal
from app.repository.auction_repository import AuctionRepository
from app.service.auction.winner_service import WinnerService

logger = logging.getLogger(__name__)


class AuctionTimerService:
    """Background sweeper that closes expired auctions."""

    POLL_INTERVAL_SECONDS = 30
    BATCH_LIMIT = 100

    def __init__(self) -> None:
        self._scheduler: Optional[object] = None
        self._running = False  # in-process re-entrancy guard

    # ------------------------------------------------------------------ #
    # Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Start the scheduler. Safe to call from FastAPI startup event.

        If APScheduler is not installed the app continues to run normally;
        auction auto-close must then be triggered externally (e.g. a cron
        that POSTs to the close endpoint, or a separate worker process).
        """
        if not _APSCHEDULER_AVAILABLE:
            logger.warning(
                "auction_timer: apscheduler not installed — "
                "automatic auction close is DISABLED. "
                "Install apscheduler to enable it."
            )
            return

        if self._scheduler is not None:
            return

        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.add_job(
            self._sweep,
            trigger=IntervalTrigger(seconds=self.POLL_INTERVAL_SECONDS),
            id="auction_timer_sweep",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        scheduler.start()
        self._scheduler = scheduler
        logger.info(
            "auction_timer.started interval=%ss batch=%s",
            self.POLL_INTERVAL_SECONDS, self.BATCH_LIMIT,
        )

    async def shutdown(self) -> None:
        if self._scheduler is None:
            return
        self._scheduler.shutdown(wait=False)  # type: ignore[union-attr]
        self._scheduler = None
        logger.info("auction_timer.stopped")

    # ------------------------------------------------------------------ #
    # Sweep                                                               #
    # ------------------------------------------------------------------ #

    async def _sweep(self) -> None:
        if self._running:
            logger.debug("auction_timer.sweep.skip already_running")
            return
        self._running = True
        try:
            await self._sweep_once()
        except Exception:  # noqa: BLE001
            logger.exception("auction_timer.sweep.error")
        finally:
            self._running = False

    async def _sweep_once(self) -> None:
        # 1) Collect candidate ids in a short-lived session.
        async with AsyncSessionLocal() as session:
            repo = AuctionRepository(session)
            expired = await repo.get_expired_auctions(limit=self.BATCH_LIMIT)
            candidate_ids = [a.id for a in expired]

        if not candidate_ids:
            return

        logger.info(
            "auction_timer.sweep candidates=%s", len(candidate_ids)
        )

        # 2) Resolve each in its own transaction. Sequential — keeps lock
        #    contention predictable; parallelize via asyncio.gather with
        #    bounded concurrency if/when needed.
        for auction_id in candidate_ids:
            await self._resolve_one(auction_id)

    @staticmethod
    async def _resolve_one(auction_id) -> None:
        try:
            async with AsyncSessionLocal() as session:
                winner_service = WinnerService(session)
                await winner_service.resolve_auction(auction_id)
        except Exception:  # noqa: BLE001
            logger.exception(
                "auction_timer.resolve.failed auction=%s", auction_id
            )


# Module-level singleton — import and call .start() / .shutdown() from FastAPI
# lifespan / startup events.
auction_timer_service = AuctionTimerService()


# Optional: convenience runner if invoked as a script for local debugging.
if __name__ == "__main__":  # pragma: no cover
    async def _main() -> None:
        auction_timer_service.start()
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            await auction_timer_service.shutdown()

    asyncio.run(_main())
