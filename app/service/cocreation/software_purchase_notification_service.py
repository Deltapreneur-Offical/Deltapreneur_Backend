"""Service for software purchase notifications."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.entity.cocreation.software_entity import Software
from app.entity.cocreation.software_purchase_entity import SoftwarePurchase
from app.service.auth.mail_service import MailService
from app.utils.cocreation_enums import SoftwarePaymentStatus

logger = logging.getLogger(__name__)


class SoftwarePurchaseNotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._mail = MailService()

    async def notify_expiring_subscriptions(self) -> int:
        """Find subscriptions expiring in the next 7 days that haven't been notified yet."""
        now = datetime.now(timezone.utc)
        target_expiry = now + timedelta(days=7)

        stmt = (
            select(SoftwarePurchase)
            .where(
                SoftwarePurchase.payment_status == SoftwarePaymentStatus.COMPLETED,
                SoftwarePurchase.expiry_date.is_not(None),
                SoftwarePurchase.expiry_date <= target_expiry,
                SoftwarePurchase.expiry_date >= now,
                SoftwarePurchase.expiry_reminder_sent_at.is_(None),
            )
            .options(
                selectinload(SoftwarePurchase.software).selectinload(Software.listed_by),
                selectinload(SoftwarePurchase.buyer),
            )
        )

        result = await self._session.execute(stmt)
        expiring_purchases = result.scalars().all()

        count = 0

        for purchase in expiring_purchases:
            if not purchase.software or not purchase.buyer:
                continue

            software_name = purchase.software.name
            buyer_email = purchase.buyer_email or purchase.buyer.email
            seller_email = (
                purchase.software.listed_by.email
                if purchase.software.listed_by
                else None
            )

            try:
                await self._mail.send_email(
                    buyer_email,
                    f"Your subscription for {software_name} is expiring soon",
                    (
                        f"Hi {purchase.buyer_full_name},\n\n"
                        f"Your subscription for {software_name} will expire on "
                        f"{purchase.expiry_date.strftime('%Y-%m-%d')}.\n\n"
                        "Thanks,\nHubRegistrar Team"
                    ),
                )

                if seller_email:
                    await self._mail.send_email(
                        seller_email,
                        f"Subscription expiring for {software_name}",
                        (
                            f"Hi,\n\nA subscription for your technology "
                            f"'{software_name}' purchased by "
                            f"{purchase.buyer_full_name} is expiring on "
                            f"{purchase.expiry_date.strftime('%Y-%m-%d')}.\n\n"
                            "Thanks,\nHubRegistrar Team"
                        ),
                    )

                await self._mail.send_email(
                    settings.ADMIN_EMAIL,
                    f"Admin Alert: Subscription expiring for {software_name}",
                    (
                        f"Technology: {software_name}\n"
                        f"Buyer: {purchase.buyer_email}\n"
                        f"Expiry: {purchase.expiry_date.strftime('%Y-%m-%d')}"
                    ),
                )

                purchase.expiry_reminder_sent_at = now
                count += 1

            except Exception:
                logger.exception(
                    "Failed to send expiry notification for purchase %s",
                    purchase.id,
                )

        if count:
            await self._session.commit()

        return count