"""Confirm OpenProvider DOMAIN_REGISTRATION managed acquisition (no Razorpay)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.core.exceptions import AppException
from app.entity.domain.openprovider_managed_acquisition_entity import (
    OpenProviderManagedAcquisition,
)
from app.entity.notification.notification_type import NotificationType
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.repository.cart_item_repository import CartItemRepository
from app.repository.openprovider_managed_acquisition_repository import (
    OpenProviderManagedAcquisitionRepository,
)
from app.service.auth.mail_service import MailService
from app.service.domain.managed_acquisition_pricing import (
    build_pricing_snapshot,
    is_managed_acquisition_payable,
)
from app.service.notification.notification_service import NotificationService
from app.utils.cart_enums import CartProductType
from app.utils.marketplace_enums import DomainEnquiryStatus

logger = logging.getLogger(__name__)


class OpenProviderManagedCartService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._cart = CartItemRepository(session)
        self._acq = OpenProviderManagedAcquisitionRepository(session)

    async def confirm(
        self,
        buyer: AppUser,
        *,
        full_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        message: str | None = None,
        item_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        items = await self._cart.get_by_user(buyer.id)
        reg_items = [
            it for it in items if it.product_type == CartProductType.DOMAIN_REGISTRATION
        ]
        other_items = [
            it for it in items if it.product_type != CartProductType.DOMAIN_REGISTRATION
        ]

        if other_items:
            raise AppException(
                "Managed domain acquisitions must be confirmed alone. "
                "Remove other cart items first.",
                status_code=400,
                code="PREMIUM_CART_ALONE",
            )
        if not reg_items:
            raise AppException("No domain registration in cart.", status_code=400)

        if item_id is not None:
            reg_items = [it for it in reg_items if it.id == item_id]
            if not reg_items:
                raise AppException("Selected cart item not found.", status_code=400)

        if len(reg_items) != 1:
            raise AppException(
                "Confirm one managed domain acquisition at a time.",
                status_code=400,
            )

        cart_item = reg_items[0]
        meta = dict(cart_item.metadata_json or {})

        # Final live revalidate before snapshot (authoritative price).
        from app.service.cart.cart_service import CartService
        from app.service.domain.domain_registration_service import DomainRegistrationService

        premium_provider = str(meta.get("premiumProvider") or "").strip().lower()
        if premium_provider in ("afternic", "sedo"):
            # Aftermarket (Afternic/Sedo) acquisition: the live aftermarket
            # check price is authoritative. GetPrice would return the standard
            # registry price for a registry-taken domain, under-recording the
            # acquisition amount, so it is never used for aftermarket items.
            domain = str(meta.get("domainName") or "").lower().strip()
            if not domain:
                raise AppException("Domain name missing from cart.", status_code=400)
            svc = DomainRegistrationService(self._session)
            check = await svc.check_registration_domain(domain)
            if check.status != "available":
                raise AppException(
                    "This domain is no longer available for acquisition.",
                    status_code=409,
                    code="SHOWCASE_AFTERMARKET_UNAVAILABLE",
                )
            try:
                unit_inr = float(getattr(check, "unitPrice") or 0)
            except (TypeError, ValueError):
                unit_inr = 0.0
            if unit_inr <= 0:
                raise AppException(
                    "Could not verify the aftermarket premium price. Try again.",
                    status_code=502,
                    code="SHOWCASE_AFTERMARKET_PRICE_FAILED",
                )
            meta.update({
                "price": unit_inr,
                "pricePerYear": unit_inr,
                "period": 1,
                "minPeriodYears": max(
                    1, int(getattr(check, "minPeriodYears") or 1)
                ),
                "priceSource": getattr(check, "priceSource") or "aftermarket_check",
                "isPremium": True,
                "registryTier": "premium",
                "premiumProvider": premium_provider,
                "isManagedAcquisition": True,
            })
        else:
            from app.integrations.openprovider.client import tld_min_registration_years

            cart_svc = CartService(self._session)
            await cart_svc._apply_registration_period_quote(
                cart_item,
                max(1, int(meta.get("period") or 1)),
                svc=DomainRegistrationService(self._session),
                tld_min_registration_years=tld_min_registration_years,
            )
            meta = dict(cart_item.metadata_json or {})
            meta["isManagedAcquisition"] = True
        cart_item.metadata_json = meta
        await self._cart.save(cart_item)

        try:
            quoted = float(meta.get("price") or 0)
        except (TypeError, ValueError):
            quoted = 0.0
        if not is_managed_acquisition_payable(quoted):
            raise AppException(
                "This domain is eligible for standard online registration checkout.",
                status_code=400,
            )

        snap = build_pricing_snapshot(meta)
        domain = str(meta.get("domainName") or "").lower().strip()
        tld = str(meta.get("tld") or "").lstrip(".").lower()
        if not domain:
            raise AppException("Domain name missing from cart.", status_code=400)
        if not tld and "." in domain:
            domain, tld = domain.split(".", 1)
        fqdn = domain if "." in domain else f"{domain}.{tld}"

        contact_name = (full_name or "").strip() or (
            f"{buyer.firstname or ''} {buyer.lastname or ''}".strip() or buyer.email
        )
        contact_email = (buyer.email or "").strip() or (email or "").strip()
        contact_phone = (phone or "").strip() or (
            getattr(buyer, "phone_number", None) or ""
        )
        contact_message = (message or "").strip() or (
            f"Managed domain acquisition request for {fqdn}."
        )
        if not contact_email:
            raise AppException(
                "A valid email is required to receive acquisition updates.",
                status_code=400,
            )

        row = OpenProviderManagedAcquisition(
            user_id=buyer.id,
            full_name=contact_name,
            email=contact_email,
            phone=contact_phone,
            message=contact_message,
            domain_name=domain.split(".")[0] if "." in domain else domain,
            tld=tld or (domain.split(".", 1)[1] if "." in domain else ""),
            period_years=int(snap["period_years"]),
            quoted_price_inr=float(snap["quoted_price_inr"]),
            payable_inr=float(snap["payable_inr"]),
            gst_inr=float(snap["gst_inr"]),
            gst_rate=snap.get("gst_rate"),
            price_per_year_inr=snap.get("price_per_year_inr"),
            provider_unit_price_inr=snap.get("provider_unit_price_inr"),
            commission_rate=snap.get("commission_rate"),
            price_source=snap.get("price_source"),
            registry_tier=str(snap.get("registry_tier") or "standard"),
            is_registry_premium=bool(snap.get("is_registry_premium")),
            pricing_snapshot_json=snap.get("pricing_snapshot_json"),
            status=DomainEnquiryStatus.PENDING.value,
        )
        await self._acq.create(row)
        await self._cart.delete_by_id(cart_item.id, buyer.id)
        await self._session.commit()
        await self._session.refresh(row)

        try:
            await MailService.send_premium_marketplace_buyer_confirmation_email(
                to_email=contact_email,
                buyer_name=contact_name,
                domain_fqdn=fqdn,
                asking_price=float(snap["payable_inr"]),
                enquiry_id=str(row.id),
            )
        except Exception:
            logger.exception("op_managed.buyer_email.failed id=%s", row.id)

        try:
            self._notify_user(
                user_id=buyer.id,
                title=f"Acquisition request received — {fqdn}",
                message=(
                    f"Thank you. HubRegistrar is personally managing your domain "
                    f"acquisition of {fqdn}. No payment is due now."
                ),
                target_url="/domains/dashboard?tab=acquisitions",
            )
        except Exception:
            logger.exception("op_managed.buyer_notify.failed id=%s", row.id)

        try:
            await MailService.send_premium_marketplace_admin_alert_email(
                domain_fqdn=fqdn,
                asking_price=float(snap["payable_inr"]),
                buyer_name=contact_name,
                buyer_email=contact_email,
                buyer_phone=contact_phone,
                message=contact_message,
                enquiry_id=str(row.id),
            )
        except Exception:
            logger.exception("op_managed.admin_email.failed id=%s", row.id)

        try:
            self._notify_admins(
                title=f"OpenProvider acquisition request — {fqdn}",
                message=f"{contact_name} requested managed acquisition of {fqdn}.",
                target_url="/admin?tab=op-managed-acquisitions",
            )
        except Exception:
            logger.exception("op_managed.admin_notify.failed id=%s", row.id)

        return {
            "success": True,
            "acquisitionId": str(row.id),
            "status": row.status,
            "domain": fqdn,
            "payableInr": float(row.payable_inr),
            "buyerEmailSentTo": contact_email,
        }

    @staticmethod
    def _notify_user(
        *,
        user_id: uuid.UUID,
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
                notification_type=NotificationType.DOMAIN_PREMIUM_ENQUIRY,
                title=title,
                message=message,
                target_url=target_url,
            )
            db.commit()
        except Exception:
            logger.exception("Failed to notify OP managed acquisition buyer")
            db.rollback()
        finally:
            db.close()

    @staticmethod
    def _notify_admins(*, title: str, message: str, target_url: str) -> None:
        db = SessionLocal()
        try:
            admins = db.query(AppUser).filter(AppUser.role == UserRole.ADMIN).all()
            for admin in admins:
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
            logger.exception("Failed to notify admins of OP managed acquisition")
            db.rollback()
        finally:
            db.close()
