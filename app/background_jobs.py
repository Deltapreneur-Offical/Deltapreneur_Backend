"""Background job orchestration for periodic backend tasks."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.service.auction.auction_timer_service import auction_timer_service
from app.service.domain.domain_registration_ops_service import (
    DomainRegistrationOpsService,
)
from app.service.domain.domain_transfer_ops_service import DomainTransferOpsService

logger = logging.getLogger(__name__)

# Stable advisory-lock key so only one API replica runs the tick at a time.
_SCHEDULER_LOCK_KEY = 874_221_903


async def _try_acquire_scheduler_lock(session) -> bool:
    result = await session.execute(
        text("SELECT pg_try_advisory_lock(:key)"),
        {"key": _SCHEDULER_LOCK_KEY},
    )
    return bool(result.scalar())


async def _release_scheduler_lock(session) -> None:
    await session.execute(
        text("SELECT pg_advisory_unlock(:key)"),
        {"key": _SCHEDULER_LOCK_KEY},
    )


async def background_scheduler() -> None:
    """
    Handles:
    - Domain retry operations
    - Expired domain orders
    - Expired software auctions
    - Expired creator (community) auctions
    """

    tick = 0
    while True:
        try:
            async with AsyncSessionLocal() as session:
                locked = await _try_acquire_scheduler_lock(session)
                if not locked:
                    logger.debug("background_scheduler.skip_tick lock_held_elsewhere")
                else:
                    try:
                        domain_ops = DomainRegistrationOpsService(session)

                        await domain_ops.run_provision_retries()
                        await domain_ops.expire_stale_orders()
                        # Every ~30s: exit stuck REGISTRATION_PENDING after timeout
                        # (UPDATE status only — never deletes/wipes rows).
                        await domain_ops.recover_stale_registration_pending()
                        tick += 1
                        if tick % 4 == 0:
                            await domain_ops.run_pending_reconcile()
                            await domain_ops.run_transfer_reconcile()
                            await domain_ops.run_stale_pending_alerts()

                        transfer_ops = DomainTransferOpsService(session)
                        transfer_stats = await transfer_ops.run_tick()
                        if any(transfer_stats.values()):
                            logger.info("Domain transfer ops tick: %s", transfer_stats)

                        # OpenProvider Premium Showcase: refresh selected rows
                        # (and replenish the unselected pool) when due. The
                        # due-check honors refresh_interval_hours, so this
                        # ~hourly cadence only acts every N hours. The scheduler
                        # advisory lock + showcase generation lock prevent
                        # concurrent runs across workers.
                        if tick % 120 == 0:  # ~ every 60 minutes
                            try:
                                from app.service.domain.showcase_domain_service import (
                                    ShowcaseDomainService,
                                )

                                showcase_stats = await ShowcaseDomainService(session).refresh_if_due()
                                if showcase_stats and not showcase_stats.get("skipped"):
                                    logger.info("showcase.refresh_if_due %s", showcase_stats)
                            except Exception:
                                logger.exception("showcase.refresh_if_due.failed")

                        from app.service.cocreation.software_auction_service import (
                            SoftwareAuctionService,
                        )

                        software_auction_service = SoftwareAuctionService(session)
                        ended_software = await software_auction_service.end_expired_auctions()
                        if ended_software:
                            logger.info(
                                "Ended %s expired software auctions",
                                ended_software,
                            )
                        from app.service.cocreation.software_purchase_notification_service import (
                            SoftwarePurchaseNotificationService,
                        )
                        notified = await SoftwarePurchaseNotificationService(session).notify_expiring_subscriptions()
                        if notified:
                            logger.info("Sent expiry notifications for %s software subscriptions", notified)

                        if settings.TECH_SUBSCRIPTION_RETRY_ENABLED:
                            try:
                                from app.service.technology.technology_subscription_retry_service import (
                                    TechnologySubscriptionRetryService,
                                )

                                tech_stats = await TechnologySubscriptionRetryService(session).run_tick()
                                if tech_stats.get("processed"):
                                    logger.info(
                                        "Technology subscription retry tick: %s",
                                        tech_stats,
                                    )
                            except Exception:
                                logger.exception("background_scheduler.technology_retry_failed")

                        from app.core.database import SessionLocal
                        from app.service.community.community_auction_service import (
                            CommunityAuctionService,
                        )

                        with SessionLocal() as sync_db:
                            ended_community = CommunityAuctionService.end_expired_auctions(sync_db)
                            if ended_community:
                                logger.info(
                                    "Ended %s expired community auctions",
                                    ended_community,
                                )

                        # Winner payment reminders (1/day) + Option A forfeit after 7 days.
                        # Uses platform_settings only — no schema changes.
                        if tick % 20 == 0:  # ~ every 10 minutes (30s ticks)
                            from app.service.auction.winner_payment_lifecycle import (
                                WinnerPaymentLifecycleAsync,
                            )

                            life = WinnerPaymentLifecycleAsync(session)
                            wstats = await life.process_reminders_and_forfeits()
                            if wstats.get("reminders") or wstats.get("forfeits"):
                                logger.info(
                                    "winner_payment.lifecycle reminders=%s forfeits=%s",
                                    wstats.get("reminders"),
                                    wstats.get("forfeits"),
                                )
                    finally:
                        try:
                            await _release_scheduler_lock(session)
                        except Exception:
                            logger.exception("background_scheduler.lock_release_failed")

        except Exception:
            logger.exception(
                "background_scheduler.tick_failed "
                "(domain retries, venture/software/community auction closure)"
            )

        await asyncio.sleep(30)


def start_background_jobs() -> asyncio.Task:
    """Start the in-process background workers and return the scheduler task."""
    auction_timer_service.start()
    return asyncio.create_task(background_scheduler())


async def stop_background_jobs() -> None:
    """Stop background workers gracefully."""
    await auction_timer_service.shutdown()
