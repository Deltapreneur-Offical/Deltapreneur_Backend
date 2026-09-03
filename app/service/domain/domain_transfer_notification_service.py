"""Emails + in-app notifications for domain transfers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.exceptions import AppException
from app.entity.domain.domain_marketplace_transaction_entity import DomainMarketplaceTransaction
from app.entity.notification.notification_type import NotificationType
from app.entity.user.app_user import AppUser
from app.repository.domain_marketplace_transaction_repository import (
    DomainMarketplaceTransactionRepository,
)
from app.service.auth.mail_service import MailService
from app.service.domain.domain_transfer_event_service import DomainTransferEventService
from app.service.notification.notification_service import NotificationService
from app.utils.transfer_enums import TransferEventType

logger = logging.getLogger(__name__)


def _transfer_url(tx_id, *, buyer: bool = False) -> str:
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    if buyer:
        return f"{base}/purchases/transfers/{tx_id}"
    return f"{base}/domains/transfers/{tx_id}"


class DomainTransferNotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DomainMarketplaceTransactionRepository(session)
        self._events = DomainTransferEventService(session)

    def _notify_sync(
        self,
        user: AppUser,
        ntype: NotificationType,
        title: str,
        message: str,
        target_url: str,
    ) -> None:
        db = SessionLocal()
        try:
            NotificationService.notify(
                db=db,
                user=user,
                notification_type=ntype,
                title=title,
                message=message,
                target_url=target_url,
            )
            db.commit()
        except Exception:
            logger.exception("transfer.notify.failed user=%s", user.id)
            db.rollback()
        finally:
            db.close()

    async def on_payment_completed(self, tx: DomainMarketplaceTransaction) -> None:
        tx = await self._repo.get_by_id(tx.id) or tx
        if tx.seller:
            if not tx.email_sale_seller_sent:
                self._notify_sync(
                    tx.seller,
                    NotificationType.DOMAIN_SOLD,
                    "Your domain was sold",
                    f"{tx.domain_fqdn} was purchased. Submit the auth code within {settings.DOMAIN_TRANSFER_SELLER_DEADLINE_HOURS} hours.",
                    _transfer_url(tx.id),
                )
                if settings.mail_configured():
                    try:
                        await MailService.send_domain_transfer_seller_sold_email(
                            tx.seller.email,
                            tx.seller.firstname or tx.seller.email,
                            tx.domain_fqdn,
                        )
                    except Exception:
                        logger.exception("transfer.email.seller_sold.failed")
                tx.email_sale_seller_sent = True
        if tx.buyer:
            if not tx.email_sale_buyer_sent:
                self._notify_sync(
                    tx.buyer,
                    NotificationType.DOMAIN_TRANSFER_AUTH_AVAILABLE,
                    "Purchase successful",
                    f"You purchased {tx.domain_fqdn}. You'll be notified when the seller submits the transfer code.",
                    _transfer_url(tx.id, buyer=True),
                )
                if settings.mail_configured():
                    try:
                        await MailService.send_domain_transfer_buyer_purchase_email(
                            tx.buyer.email,
                            tx.buyer.firstname or tx.buyer.email,
                            tx.domain_fqdn,
                            _transfer_url(tx.id, buyer=True),
                        )
                    except Exception:
                        logger.exception("transfer.email.buyer_purchase.failed")
                tx.email_sale_buyer_sent = True
        await self._repo.save(tx)

    async def on_auth_code_available(self, tx: DomainMarketplaceTransaction) -> None:
        tx = await self._repo.get_by_id(tx.id) or tx
        if tx.buyer and not tx.email_auth_available_sent:
            self._notify_sync(
                tx.buyer,
                NotificationType.DOMAIN_TRANSFER_AUTH_AVAILABLE,
                "Auth code ready",
                f"The seller submitted the transfer code for {tx.domain_fqdn}. Open your purchase to reveal it.",
                _transfer_url(tx.id, buyer=True),
            )
            if settings.mail_configured():
                try:
                    await MailService.send_domain_transfer_auth_available_email(
                        tx.buyer.email,
                        tx.buyer.firstname or tx.buyer.email,
                        tx.domain_fqdn,
                        _transfer_url(tx.id, buyer=True),
                    )
                except Exception:
                    logger.exception("transfer.email.auth_available.failed")
            tx.email_auth_available_sent = True
            await self._repo.save(tx)

    async def on_admin_review_required(self, tx: DomainMarketplaceTransaction) -> None:
        if tx.email_admin_review_sent:
            return
        if tx.seller:
            self._notify_sync(
                tx.seller,
                NotificationType.DOMAIN_TRANSFER_ADMIN_REVIEW_REQUIRED,
                "Transfer deadline passed",
                f"Admin review is required for {tx.domain_fqdn}.",
                _transfer_url(tx.id),
            )
        if tx.buyer:
            self._notify_sync(
                tx.buyer,
                NotificationType.DOMAIN_TRANSFER_ADMIN_REVIEW_REQUIRED,
                "Transfer under review",
                f"HubRegistrar is reviewing the transfer for {tx.domain_fqdn}.",
                _transfer_url(tx.id, buyer=True),
            )
        tx.email_admin_review_sent = True
        await self._repo.save(tx)

    async def on_payout_released(self, tx: DomainMarketplaceTransaction) -> None:
        if tx.seller and not tx.email_payout_released_sent:
            self._notify_sync(
                tx.seller,
                NotificationType.DOMAIN_TRANSFER_PAYOUT_RELEASED,
                "Payout released",
                f"Payout for {tx.domain_fqdn} has been approved.",
                _transfer_url(tx.id),
            )
            tx.email_payout_released_sent = True
            await self._repo.save(tx)

    async def on_payout_profile_reminder(
        self,
        tx: DomainMarketplaceTransaction,
        *,
        admin: AppUser,
    ) -> str:
        tx = await self._repo.get_by_id(tx.id) or tx
        if not tx.seller or not tx.seller.email:
            raise AppException("Seller email address is not available.", status_code=400)
        if not settings.mail_configured():
            raise AppException("Unable to send reminder.", status_code=503)

        payout_settings_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/settings/payouts"
        await MailService.send_seller_payout_details_reminder_email(
            to_email=tx.seller.email,
            payout_settings_url=payout_settings_url,
        )
        now = datetime.now(timezone.utc)
        tx.payout_reminder_sent_at = now
        tx.payout_reminder_count = int(tx.payout_reminder_count or 0) + 1
        self._notify_sync(
            tx.seller,
            NotificationType.SYSTEM,
            "Add payout details",
            f"Please add your payout details so HubRegistrar can release payment for {tx.domain_fqdn}.",
            payout_settings_url,
        )
        await self._events.log(
            tx.id,
            TransferEventType.PAYOUT_REMINDER_SENT,
            actor_user_id=admin.id,
            actor_role="ADMIN",
            payload={"recipient": tx.seller.email, "reminderCount": tx.payout_reminder_count},
        )
        await self._repo.save(tx)
        return tx.seller.email

    async def on_refund(self, tx: DomainMarketplaceTransaction) -> None:
        if tx.buyer and not tx.email_refund_sent:
            self._notify_sync(
                tx.buyer,
                NotificationType.DOMAIN_TRANSFER_REFUNDED,
                "Refund processed",
                f"Your purchase of {tx.domain_fqdn} has been refunded.",
                _transfer_url(tx.id, buyer=True),
            )
            tx.email_refund_sent = True
            await self._repo.save(tx)
