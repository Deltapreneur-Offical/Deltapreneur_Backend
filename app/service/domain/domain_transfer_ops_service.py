"""Background jobs: seller reminders, admin-review escalation, WHOIS poll."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repository.domain_marketplace_transaction_repository import (
    DomainMarketplaceTransactionRepository,
)
from app.service.auth.mail_service import MailService
from app.service.domain.domain_transfer_event_service import DomainTransferEventService
from app.service.domain.domain_transfer_notification_service import (
    DomainTransferNotificationService,
)
from app.service.domain.domain_transfer_whois_service import DomainTransferWhoisService
from app.utils.transfer_enums import MarketplaceTransferStatus, TransferEventType

logger = logging.getLogger(__name__)


class DomainTransferOpsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DomainMarketplaceTransactionRepository(session)
        self._events = DomainTransferEventService(session)
        self._notify = DomainTransferNotificationService(session)
        self._whois = DomainTransferWhoisService(session)

    async def run_tick(self) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        limit = settings.DOMAIN_TRANSFER_OPS_BATCH_LIMIT
        stats = {"timeouts": 0, "reminders_12h": 0, "reminders_6h": 0, "whois": 0}

        for tx in await self._repo.list_seller_deadline_candidates(now, limit=limit):
            tx.transfer_status = MarketplaceTransferStatus.ADMIN_REVIEW_REQUIRED
            tx.admin_review_required_at = now
            tx.admin_review_reason = "SELLER_AUTH_CODE_TIMEOUT"
            await self._repo.save(tx)
            await self._events.log(
                tx.id,
                TransferEventType.ADMIN_REVIEW,
                actor_role="SYSTEM",
                payload={"reason": "SELLER_AUTH_CODE_TIMEOUT"},
            )
            await self._notify.on_admin_review_required(tx)
            stats["timeouts"] += 1

        for tx in await self._repo.list_reminder_candidates(
            now, hours_before=12, reminder_field="email_seller_reminder_12h_sent", limit=limit,
        ):
            if tx.seller and settings.mail_configured():
                try:
                    await MailService.send_domain_transfer_seller_reminder_email(
                        tx.seller.email,
                        tx.seller.firstname or tx.seller.email,
                        tx.domain_fqdn,
                        hours_remaining=12,
                    )
                except Exception:
                    logger.exception("transfer.reminder.12h.failed tx=%s", tx.id)
            tx.email_seller_reminder_12h_sent = True
            await self._repo.save(tx)
            stats["reminders_12h"] += 1

        for tx in await self._repo.list_reminder_candidates(
            now, hours_before=6, reminder_field="email_seller_reminder_6h_sent", limit=limit,
        ):
            if tx.seller and settings.mail_configured():
                try:
                    await MailService.send_domain_transfer_seller_reminder_email(
                        tx.seller.email,
                        tx.seller.firstname or tx.seller.email,
                        tx.domain_fqdn,
                        hours_remaining=6,
                    )
                except Exception:
                    logger.exception("transfer.reminder.6h.failed tx=%s", tx.id)
            tx.email_seller_reminder_6h_sent = True
            await self._repo.save(tx)
            stats["reminders_6h"] += 1

        whois_count = await self._whois.poll_in_progress(limit=limit)
        stats["whois"] = whois_count

        if any(stats.values()):
            await self._session.commit()
        return stats
