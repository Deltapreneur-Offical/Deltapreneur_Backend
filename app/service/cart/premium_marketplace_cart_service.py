"""Premium marketplace domain cart confirmation (no Razorpay).

Marketplace listings above ₹5L only — not OpenProvider registration.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.core.exceptions import AppException
from app.entity.notification.notification_type import NotificationType
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.repository.cart_item_repository import CartItemRepository
from app.repository.domain_listing_repository import DomainListingRepository
from app.service.auth.mail_service import MailService
from app.service.domain.domain_enquiry_service import (
    DOMAIN_UNAVAILABLE_MSG,
    DomainEnquiryService,
    is_premium_marketplace_listing,
)
from app.service.notification.notification_service import NotificationService
from app.utils.cart_enums import CartProductType
from app.utils.marketplace_enums import DomainListingStatus

logger = logging.getLogger(__name__)


class PremiumMarketplaceCartService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._cart = CartItemRepository(session)
        self._listings = DomainListingRepository(session)
        self._enquiries = DomainEnquiryService(session)

    async def confirm(
        self,
        buyer: AppUser,
        *,
        full_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        message: str | None = None,
        listing_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        items = await self._cart.get_by_user(buyer.id)
        listing_items = [
            it for it in items if it.product_type == CartProductType.DOMAIN_LISTING
        ]
        other_items = [
            it for it in items if it.product_type != CartProductType.DOMAIN_LISTING
        ]

        if other_items:
            raise AppException(
                "Premium domains above ₹5,00,000 use a dedicated managed acquisition "
                "checkout and cannot be mixed with other cart items.",
                status_code=400,
                code="PREMIUM_CART_ALONE",
            )
        if not listing_items:
            raise AppException("No marketplace domain in cart.", status_code=400)

        if listing_id is not None:
            listing_items = [it for it in listing_items if it.product_id == listing_id]
            if not listing_items:
                raise AppException("Selected domain is not in your cart.", status_code=400)

        if len(listing_items) != 1:
            raise AppException(
                "Confirm one premium marketplace domain at a time.",
                status_code=400,
            )

        cart_item = listing_items[0]
        listing = await self._listings.get_by_id_for_update(cart_item.product_id)
        if listing is None:
            raise AppException("Domain listing not found.", status_code=404)

        if listing.domain_status == DomainListingStatus.UNDER_REVIEW:
            raise AppException(DOMAIN_UNAVAILABLE_MSG, status_code=409)
        if listing.domain_status != DomainListingStatus.AVAILABLE:
            raise AppException(DOMAIN_UNAVAILABLE_MSG, status_code=409)
        if not is_premium_marketplace_listing(listing):
            raise AppException(
                "This checkout is only for marketplace domains above ₹5,00,000.",
                status_code=400,
            )
        if listing.listed_by_user_id == buyer.id:
            raise AppException("You cannot acquire your own listing.", status_code=400)

        fqdn = f"{listing.domain_name}{listing.domain_extension or ''}"
        contact_name = (full_name or "").strip() or (
            f"{buyer.firstname or ''} {buyer.lastname or ''}".strip() or buyer.email
        )
        # Always prefer the authenticated account email so buyers reliably receive mail
        # even when testing as admin+buyer or with alternate contact fields.
        account_email = (buyer.email or "").strip()
        contact_email = account_email or (email or "").strip()
        contact_phone = (phone or "").strip() or (
            getattr(buyer, "phone_number", None) or ""
        )
        contact_message = (message or "").strip() or (
            f"Premium marketplace acquisition request for {fqdn}."
        )
        if not contact_email:
            raise AppException(
                "A valid email is required to receive acquisition updates.",
                status_code=400,
            )

        enquiry = await self._enquiries.submit(
            listing.id,
            enquirer=buyer,
            full_name=contact_name,
            email=contact_email,
            phone=contact_phone,
            message=contact_message,
            listing_locked=listing,
            skip_commit=True,
        )

        listing.domain_status = DomainListingStatus.UNDER_REVIEW
        await self._listings.save(listing)
        await self._cart.delete_by_id(cart_item.id, buyer.id)
        await self._session.commit()

        # Buyer email + in-app notification (independent of admin role).
        try:
            await MailService.send_premium_marketplace_buyer_confirmation_email(
                to_email=contact_email,
                buyer_name=contact_name,
                domain_fqdn=fqdn,
                asking_price=float(listing.asking_price or 0),
                enquiry_id=enquiry["id"],
            )
        except Exception:
            logger.exception(
                "premium_marketplace.buyer_email.failed enquiry=%s to=%s",
                enquiry["id"],
                contact_email,
            )

        try:
            self._notify_user(
                user_id=buyer.id,
                notification_type=NotificationType.DOMAIN_PREMIUM_ENQUIRY,
                title=f"Acquisition request received — {fqdn}",
                message=(
                    f"Thank you. HubRegistrar is personally managing your premium "
                    f"acquisition of {fqdn}. No payment is due now — we will contact you shortly."
                ),
                target_url="/cart",
            )
        except Exception:
            logger.exception(
                "premium_marketplace.buyer_notify.failed enquiry=%s", enquiry["id"]
            )

        try:
            await MailService.send_premium_marketplace_admin_alert_email(
                domain_fqdn=fqdn,
                asking_price=float(listing.asking_price or 0),
                buyer_name=contact_name,
                buyer_email=contact_email,
                buyer_phone=contact_phone,
                message=contact_message,
                enquiry_id=enquiry["id"],
            )
        except Exception:
            logger.exception(
                "premium_marketplace.admin_email.failed enquiry=%s", enquiry["id"]
            )

        try:
            self._notify_admins(
                title=f"Premium acquisition request — {fqdn}",
                message=f"{contact_name} requested acquisition of {fqdn}.",
                target_url="/admin?tab=domain-enquiries",
                exclude_user_id=None,  # Admin-as-buyer still gets admin alert + buyer notice above
            )
        except Exception:
            logger.exception(
                "premium_marketplace.admin_notify.failed enquiry=%s", enquiry["id"]
            )

        return {
            "success": True,
            "enquiryId": enquiry["id"],
            "listingId": str(listing.id),
            "status": enquiry["status"],
            "domainStatus": DomainListingStatus.UNDER_REVIEW.value,
            "domain": fqdn,
            "buyerEmailSentTo": contact_email,
        }

    @staticmethod
    def _notify_user(
        *,
        user_id: uuid.UUID,
        notification_type: NotificationType,
        title: str,
        message: str,
        target_url: str,
    ) -> None:
        db = SessionLocal()
        try:
            user = db.query(AppUser).filter(AppUser.id == user_id).first()
            if user is None:
                return
            NotificationService.notify(
                db,
                user=user,
                notification_type=notification_type,
                title=title,
                message=message,
                target_url=target_url,
            )
            db.commit()
        except Exception:
            logger.exception("Failed to notify premium acquisition user")
            db.rollback()
        finally:
            db.close()

    @staticmethod
    def _notify_admins(
        *,
        title: str,
        message: str,
        target_url: str,
        exclude_user_id: uuid.UUID | None = None,
    ) -> None:
        db = SessionLocal()
        try:
            admins = (
                db.query(AppUser)
                .filter(AppUser.role == UserRole.ADMIN)
                .all()
            )
            for admin in admins:
                if exclude_user_id is not None and admin.id == exclude_user_id:
                    continue
                NotificationService.notify(
                    db,
                    user=admin,
                    notification_type=NotificationType.DOMAIN_PREMIUM_ENQUIRY,
                    title=title,
                    message=message,
                    target_url=target_url,
                )
            db.commit()
        except Exception:
            logger.exception("Failed to notify admins of premium marketplace enquiry")
            db.rollback()
        finally:
            db.close()
