"""Razorpay purchase flow for software listings."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)
from app.entity.cobrother.cobrother_request_entity import CoBrotherRequest
from app.entity.cocreation.software_purchase_entity import SoftwarePurchase
from app.entity.cocreation.software_auction import SoftwareAuction
from app.entity.user.app_user import AppUser
from app.integrations.razorpay import client as rzp
from app.repository.cobrother_request_repository import CoBrotherRequestRepository
from app.repository.software_purchase_repository import SoftwarePurchaseRepository
from app.repository.software_repository import SoftwareRepository
from app.service.auth.mail_service import MailService
from app.utils.addon_services import parse_addon_services, resolve_buyer_phone
from app.service.cocreation.technology_verification_guard import assert_technology_purchasable
from app.utils.cocreation_enums import (
    SoftwarePaymentStatus,
    SoftwarePurchaseCompletionStatus,
    SoftwarePurchaseType,
    SoftwareStatus,
    TechnologyType,
    TechnologyPricingPlanDuration,
)
from app.utils.marketplace_enums import CoBrotherRequestStatus, CoBrotherRequestType
from app.service.currency.exchange_rate_service import convert_inr
from app.service.platform.listing_pricing_service import ListingPricingService


def snapshot_delivery(purchase: SoftwarePurchase, software) -> None:
    if software is None or getattr(purchase, "delivered_at", None) is not None:
        return
    if not hasattr(purchase, "delivered_github_link"):
        return
    purchase.delivered_github_link = software.github_link
    purchase.delivered_documentation_urls = getattr(software, "documentation_urls", None)
    purchase.delivered_download_urls = getattr(software, "download_urls", None)
    purchase.delivered_at = datetime.now(timezone.utc)


def buyer_delivery_github(purchase: SoftwarePurchase, software) -> str:
    """Return the buyer-facing GitHub URL for Software deliveries only.

    Hardware listings never expose a repository URL to the buyer, even if one
    is stored on the listing or purchase snapshot.
    """
    if software is not None and getattr(software, "technology_type", None) == TechnologyType.HARDWARE:
        return ""
    snap = getattr(purchase, "delivered_github_link", None)
    if snap:
        return snap
    return (software.github_link if software else "") or ""


def should_mark_listing_sold(software, purchase: SoftwarePurchase) -> bool:
    if software is None:
        return False
    if software.purchase_type == SoftwarePurchaseType.SUBSCRIPTION:
        return False
    if (
        purchase.selected_plan
        and purchase.selected_plan != TechnologyPricingPlanDuration.ONE_TIME
    ):
        return False
    return True


class CocreationPaymentService:
    COBROTHER_FEE_INR = 1000.0

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._software_repo = SoftwareRepository(session)
        self._purchase_repo = SoftwarePurchaseRepository(session)
        self._cobrother_repo = CoBrotherRequestRepository(session)
        self._pricing = ListingPricingService(session)

    async def create_purchase_order(
        self,
        software_id: uuid.UUID,
        *,
        buyer: AppUser,
        co_brother_opt_in: bool = False,
        addon_amount: float = 0.0,
        buyer_full_name: str = "",
        buyer_email: str = "",
        buyer_phone: str = "",
        selected_addon_services: str = "",
        addon_services: list | None = None,
        selected_plan_duration: str | None = None,
        currency: str = "INR",
        redeem_points: bool = False,
    ) -> dict[str, Any]:
        software = await self._software_repo.get_by_id(software_id)
        if software is None:
            raise AppException("Software listing not found.", status_code=404)
        if software.listed_by_user_id == buyer.id:
            raise AppException("You cannot buy your own listing.", status_code=400)
        assert_technology_purchasable(software)
        if software.software_status != SoftwareStatus.AVAILABLE:
            raise AppException("Software is not available.", status_code=400)
        if software.purchase_type == SoftwarePurchaseType.AUCTION:
            raise AppException(
                "This listing is on auction. Use the auction page to place a bid.",
                status_code=400,
            )
        if await self._purchase_repo.has_completed_purchase(software_id, buyer.id):
            raise AppException("You have already purchased this software.", status_code=409)

        if not rzp.is_configured():
            raise AppException(
                "Payment gateway is not configured.",
                status_code=503,
            )

        parsed_addon_amount, parsed_addon_keys = parse_addon_services(addon_services)
        if parsed_addon_keys and not selected_addon_services:
            selected_addon_services = parsed_addon_keys
        if parsed_addon_amount > 0 and addon_amount <= 0:
            addon_amount = parsed_addon_amount

        service_keys: list[str] = [
            k.strip() for k in (selected_addon_services or "").split(",") if k.strip()
        ]
        if co_brother_opt_in and "COBROTHER_HELPER" not in service_keys:
            service_keys.insert(0, "COBROTHER_HELPER")
        selected_addon_services = ",".join(service_keys)

        phone = resolve_buyer_phone(buyer_phone, buyer)

        base_price = software.price
        seller_price = software.seller_price
        plan_enum = None
        if selected_plan_duration:
            key_mapping = {
                "1_MONTH": "ONE_MONTH",
                "3_MONTHS": "THREE_MONTHS",
                "6_MONTHS": "SIX_MONTHS",
                "12_MONTHS": "TWELVE_MONTHS",
            }
            mapped_duration = key_mapping.get(selected_plan_duration, selected_plan_duration)
            try:
                plan_enum = TechnologyPricingPlanDuration(mapped_duration)
            except ValueError:
                pass
            if software.pricing_plans:
                plan = next((p for p in software.pricing_plans if p.plan_duration == plan_enum and p.is_active), None)
                if plan:
                    base_price = plan.price

        # Commission logic
        is_software = software.technology_type == TechnologyType.SOFTWARE
        is_subscription = plan_enum is not None and plan_enum != TechnologyPricingPlanDuration.ONE_TIME

        if is_software and is_subscription:
            # 100% to HubRegistrar
            platform_fee = base_price
            seller_payout = 0.0
        else:
            seller_payout = seller_price if seller_price is not None else 0.0
            platform_fee = round(base_price - seller_payout, 2)


        co_brother_fee = self.COBROTHER_FEE_INR if co_brother_opt_in else 0.0
        sub_total = base_price + co_brother_fee + addon_amount
        total_inr = sub_total * 1.18

        charge_currency = currency.upper()
        charge_amount = total_inr

        if charge_currency != "INR":
            try:
                conversion = convert_inr(total_inr, charge_currency)
                charge_amount = conversion["converted"]
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "cocreation.purchase.currency_conversion_failed currency=%s err=%s",
                    charge_currency, exc,
                )
                raise AppException(
                    f"Currency {charge_currency} is not supported for checkout.",
                    status_code=400,
                ) from exc

        receipt = f"sw_{str(software_id).replace('-', '')[:16]}"
        try:
            rzp_order = rzp.create_order(
                amount_inr=charge_amount,
                receipt=receipt,
                currency=charge_currency,
                notes={"softwareId": str(software_id), "buyerId": str(buyer.id)},
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("razorpay.create_order.failed software=%s", software_id)
            msg = str(exc)
            if "currency" in msg.lower() or "unsupported" in msg.lower():
                raise AppException(
                    f"Currency {charge_currency} is not supported by the payment gateway.",
                    status_code=400,
                ) from exc
            raise AppException(
                "Could not create payment order. Please try again.",
                status_code=502,
            ) from exc

        purchase = SoftwarePurchase(
            software_id=software_id,
            buyer_id=buyer.id,
            buyer_full_name=buyer_full_name or f"{buyer.firstname or ''} {buyer.lastname or ''}".strip(),
            buyer_email=buyer_email or buyer.email,
            buyer_phone=phone,
            purchase_addon_services=(selected_addon_services or "").strip() or None,
            razorpay_order_id=rzp_order["id"],
            payment_status=SoftwarePaymentStatus.CREATED,
            co_brother_opt_in=co_brother_opt_in,
            selected_plan=plan_enum,
            gross_amount_inr=base_price,
            platform_fee_inr=platform_fee,
            seller_payout_inr=seller_payout,
        )
        await self._purchase_repo.create(purchase)
        await self._session.commit()

        return {
            "orderId": rzp_order["id"],
            "amount": charge_amount,
            "basePrice": base_price,
            "coBrotherFee": co_brother_fee,
            "addonAmount": addon_amount,
            "coBrotherOptIn": co_brother_opt_in,
            "currency": charge_currency,
            "softwareId": str(software_id),
            "keyId": rzp.get_key_id(),
        }

    async def create_pending_from_cart(
        self,
        *,
        software,
        buyer: AppUser,
        razorpay_order_id: str,
        buyer_full_name: str,
        buyer_email: str,
        buyer_phone: str,
        selected_plan: str | None,
        addon_services: str | None,
        co_brother_opt_in: bool,
    ) -> SoftwarePurchase:
        assert_technology_purchasable(software)
        existing = await self._purchase_repo.get_by_order_and_software(
            razorpay_order_id, software.id
        )
        if existing is not None:
            return existing

        plan_enum = None
        base_price = float(software.price or 0)
        if selected_plan:
            key_mapping = {
                "1_MONTH": "ONE_MONTH",
                "3_MONTHS": "THREE_MONTHS",
                "6_MONTHS": "SIX_MONTHS",
                "12_MONTHS": "TWELVE_MONTHS",
            }
            mapped = key_mapping.get(selected_plan, selected_plan)
            try:
                plan_enum = TechnologyPricingPlanDuration(mapped)
            except ValueError:
                plan_enum = None
            if software.pricing_plans and plan_enum:
                plan = next(
                    (
                        p
                        for p in software.pricing_plans
                        if p.plan_duration == plan_enum and p.is_active
                    ),
                    None,
                )
                if plan:
                    base_price = float(plan.price)
        is_software = software.technology_type == TechnologyType.SOFTWARE
        is_subscription = (
            plan_enum is not None and plan_enum != TechnologyPricingPlanDuration.ONE_TIME
        )
        if is_software and is_subscription:
            platform_fee = base_price
            seller_payout = 0.0
        else:
            seller_payout = (
                float(software.seller_price) if software.seller_price is not None else 0.0
            )
            platform_fee = round(base_price - seller_payout, 2)

        purchase = SoftwarePurchase(
            software_id=software.id,
            buyer_id=buyer.id,
            buyer_full_name=buyer_full_name,
            buyer_email=buyer_email,
            buyer_phone=buyer_phone,
            purchase_addon_services=addon_services or None,
            razorpay_order_id=razorpay_order_id,
            payment_status=SoftwarePaymentStatus.CREATED,
            co_brother_opt_in=co_brother_opt_in,
            selected_plan=plan_enum,
            gross_amount_inr=base_price,
            platform_fee_inr=platform_fee,
            seller_payout_inr=seller_payout,
        )
        return await self._purchase_repo.create(purchase)

    async def verify_payment(
        self,
        software_id: uuid.UUID,
        *,
        razorpay_payment_id: str,
        razorpay_order_id: str,
        razorpay_signature: str,
        buyer: AppUser,
    ) -> dict[str, Any]:
        purchases = await self._purchase_repo.list_by_razorpay_order_id_for_update(
            razorpay_order_id
        )
        purchase = next((p for p in purchases if p.software_id == software_id), None)
        if purchase is None:
            raise AppException("Purchase not found.", status_code=404)
        if purchase.buyer_id != buyer.id:
            raise AppException(
                "This purchase order belongs to another user.",
                status_code=403,
            )
        if purchase.payment_status == SoftwarePaymentStatus.REFUNDED:
            raise AppException("This purchase has been refunded.", status_code=400)

        if not rzp.verify_payment_signature(
            razorpay_order_id, razorpay_payment_id, razorpay_signature,
        ):
            raise AppException("Verification failed.", status_code=400)

        software = purchase.software or await self._software_repo.get_by_id(software_id)
        if purchase.payment_status == SoftwarePaymentStatus.COMPLETED:
            snapshot_delivery(purchase, software)
            await self._purchase_repo.save(purchase)
            await self._session.commit()
            return {
                "success": True,
                "message": "Payment already verified.",
                "githubLink": buyer_delivery_github(purchase, software),
                "purchaseId": str(purchase.id),
                "completionStatus": purchase.completion_status.value,
            }

        await self._finalize_paid_purchase(
            purchase,
            software=software,
            razorpay_payment_id=razorpay_payment_id,
            buyer=buyer,
        )
        await self._session.commit()
        return {
            "success": True,
            "message": "Payment successful",
            "githubLink": buyer_delivery_github(purchase, software),
            "purchaseId": str(purchase.id),
            "completionStatus": SoftwarePurchaseCompletionStatus.CONFIRMED.value,
        }

    async def complete_from_webhook(
        self,
        razorpay_order_id: str,
        razorpay_payment_id: str,
    ) -> dict[str, Any]:
        purchases = await self._purchase_repo.list_by_razorpay_order_id_for_update(
            razorpay_order_id
        )
        completed = 0
        skipped = 0
        for purchase in purchases:
            if purchase.payment_status in (
                SoftwarePaymentStatus.REFUNDED,
            ):
                skipped += 1
                continue
            if purchase.payment_status == SoftwarePaymentStatus.COMPLETED:
                software = purchase.software or await self._software_repo.get_by_id(
                    purchase.software_id
                )
                snapshot_delivery(purchase, software)
                if not purchase.razorpay_payment_id:
                    purchase.razorpay_payment_id = razorpay_payment_id
                await self._purchase_repo.save(purchase)
                skipped += 1
                continue
            software = purchase.software or await self._software_repo.get_by_id(
                purchase.software_id
            )
            await self._finalize_paid_purchase(
                purchase,
                software=software,
                razorpay_payment_id=razorpay_payment_id,
                buyer=None,
            )
            completed += 1
        if purchases:
            await self._session.commit()
        return {
            "purchasesFound": len(purchases),
            "purchasesCompleted": completed,
            "purchasesSkipped": skipped,
        }

    async def mark_failed_from_webhook(self, razorpay_order_id: str) -> int:
        purchases = await self._purchase_repo.list_by_razorpay_order_id_for_update(
            razorpay_order_id
        )
        updated = 0
        for purchase in purchases:
            if purchase.payment_status != SoftwarePaymentStatus.CREATED:
                continue
            purchase.payment_status = SoftwarePaymentStatus.FAILED
            await self._purchase_repo.save(purchase)
            updated += 1
        if updated:
            await self._session.commit()
        return updated

    async def mark_refunded_from_webhook(
        self,
        razorpay_order_id: str,
        refund_id: str | None,
    ) -> int:
        purchases = await self._purchase_repo.list_by_razorpay_order_id_for_update(
            razorpay_order_id
        )
        updated = 0
        now = datetime.now(timezone.utc)
        for purchase in purchases:
            if purchase.payment_status == SoftwarePaymentStatus.REFUNDED:
                continue
            if purchase.seller_paid_at:
                continue
            purchase.payment_status = SoftwarePaymentStatus.REFUNDED
            purchase.razorpay_refund_id = refund_id or purchase.razorpay_refund_id
            purchase.refund_completed_at = now
            await self._purchase_repo.save(purchase)
            await self._restore_listing_if_exclusive(purchase)
            updated += 1
        if updated:
            await self._session.commit()
        return updated

    async def _finalize_paid_purchase(
        self,
        purchase: SoftwarePurchase,
        *,
        software,
        razorpay_payment_id: str,
        buyer: AppUser | None,
    ) -> None:
        if purchase.payment_status == SoftwarePaymentStatus.COMPLETED:
            snapshot_delivery(purchase, software)
            return

        now = datetime.now(timezone.utc)
        purchase.payment_status = SoftwarePaymentStatus.COMPLETED
        purchase.completion_status = SoftwarePurchaseCompletionStatus.CONFIRMED
        purchase.razorpay_payment_id = razorpay_payment_id
        purchase.sold_at = now
        snapshot_delivery(purchase, software)
        if purchase.co_brother_opt_in:
            purchase.co_brother_help_paid = True

        if purchase.selected_plan and not purchase.expiry_date:
            if purchase.selected_plan == TechnologyPricingPlanDuration.ONE_MONTH:
                purchase.expiry_date = now + timedelta(days=30)
            elif purchase.selected_plan == TechnologyPricingPlanDuration.THREE_MONTHS:
                purchase.expiry_date = now + timedelta(days=90)
            elif purchase.selected_plan == TechnologyPricingPlanDuration.SIX_MONTHS:
                purchase.expiry_date = now + timedelta(days=180)
            elif purchase.selected_plan == TechnologyPricingPlanDuration.TWELVE_MONTHS:
                purchase.expiry_date = now + timedelta(days=365)

        if software and should_mark_listing_sold(software, purchase):
            software.software_status = SoftwareStatus.SOLD
            await self._software_repo.save(software)

        await self._purchase_repo.save(purchase)
        await self._create_cobrother_request(purchase, software)

        from app.utils.addon_services import create_addon_operations_requests
        buyer_phone = purchase.buyer_phone or (
            buyer.phone_number if buyer else ""
        )
        buyer_email = purchase.buyer_email or (buyer.email if buyer else "")
        buyer_name = purchase.buyer_full_name or (
            " ".join(p for p in (buyer.firstname, buyer.lastname) if p).strip()
            if buyer
            else ""
        )
        await create_addon_operations_requests(
            self._session,
            user_id=purchase.buyer_id,
            buyer_name=buyer_name,
            buyer_email=buyer_email,
            buyer_phone=buyer_phone,
            addon_services_csv=purchase.purchase_addon_services,
        )
        await self._send_receipt_email(purchase, software)
        await self._send_seller_sold_notification_email(purchase, software)

        from app.service.platform.track_record_service import (
            TrackRecordService,
            TrackRecordCategory,
            PaymentStatus,
            FulfillmentStatus,
            OverallStatus,
        )
        await TrackRecordService(self._session).record_paid_attempt(
            internal_order_id=f"TRK-TECH-{purchase.razorpay_order_id}",
            category=TrackRecordCategory.TECHNOLOGY_PURCHASE,
            provider_subcategory="Razorpay",
            item_name=software.name if software else str(purchase.software_id),
            item_id=str(purchase.software_id),
            buyer_name=purchase.buyer_full_name or "",
            buyer_email=purchase.buyer_email or "",
            buyer_phone=purchase.buyer_phone or "",
            buyer_user_id=purchase.buyer_id,
            amount_charged=float(purchase.gross_amount_inr or 0.0),
            currency="INR",
            payment_status=PaymentStatus.CAPTURED,
            razorpay_order_id=purchase.razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            fulfillment_status=FulfillmentStatus.PROVISIONED,
            overall_status=OverallStatus.SUCCESS,
        )

    async def _restore_listing_if_exclusive(self, purchase: SoftwarePurchase) -> None:
        software = purchase.software or await self._software_repo.get_by_id(
            purchase.software_id
        )
        if software is None or not should_mark_listing_sold(software, purchase):
            return
        remaining = await self._purchase_repo.count_completed_for_software(software.id)
        if remaining == 0:
            software.software_status = SoftwareStatus.AVAILABLE
            await self._software_repo.save(software)

    async def complete_auction_winner_purchase(
        self,
        *,
        auction: SoftwareAuction,
        buyer: AppUser,
        razorpay_order_id: str,
        razorpay_payment_id: str,
    ) -> SoftwarePurchase:
        """Finalize a software auction sale after verified winner payment."""
        existing = await self._purchase_repo.get_by_razorpay_order_id(razorpay_order_id)
        if existing is not None:
            return existing

        software = await self._software_repo.get_by_id(auction.software_id)
        if software is None:
            raise AppException("Software listing not found.", status_code=404)

        base_price = float(auction.current_highest_bid or 0)
        if base_price <= 0:
            raise AppException("Invalid winning bid amount.", status_code=400)

        list_price = float(software.price or 0)
        seller_price = software.seller_price
        if seller_price is not None and list_price > 0:
            seller_payout = round(base_price * (float(seller_price) / list_price), 2)
        elif seller_price is not None:
            seller_payout = round(min(float(seller_price), base_price), 2)
        else:
            seller_payout = 0.0
        platform_fee = round(base_price - seller_payout, 2)

        buyer_name = (
            f"{buyer.firstname or ''} {buyer.lastname or ''}".strip()
            or buyer.email
        )
        now = datetime.now(timezone.utc)
        purchase = SoftwarePurchase(
            software_id=auction.software_id,
            buyer_id=buyer.id,
            buyer_full_name=buyer_name,
            buyer_email=buyer.email,
            buyer_phone=buyer.phone_number,
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            payment_status=SoftwarePaymentStatus.COMPLETED,
            completion_status=SoftwarePurchaseCompletionStatus.CONFIRMED,
            gross_amount_inr=base_price,
            platform_fee_inr=platform_fee,
            seller_payout_inr=seller_payout,
            sold_at=now,
        )
        await self._purchase_repo.create(purchase)

        software.software_status = SoftwareStatus.SOLD
        await self._software_repo.save(software)
        snapshot_delivery(purchase, software)

        await self._create_cobrother_request(purchase, software)
        await self._send_receipt_email(purchase, software)
        await self._send_seller_sold_notification_email(purchase, software)
        return purchase

    async def handle_failure(self, software_id: uuid.UUID, *, buyer: AppUser) -> dict:
        purchase = await self._purchase_repo.find_latest_created(software_id, buyer.id)
        if purchase and not purchase.razorpay_payment_id:
            purchase.payment_status = SoftwarePaymentStatus.FAILED
            await self._purchase_repo.save(purchase)
            await self._session.commit()
        return {"success": False}

    async def cancel_unpaid_purchase(
        self,
        purchase_id: uuid.UUID,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        purchase = await self._purchase_repo.get_by_id_for_update(purchase_id)
        if purchase is None:
            raise AppException("Purchase not found.", status_code=404)
        if purchase.buyer_id != buyer.id:
            raise AppException("You can only cancel your own purchases.", status_code=403)
        if purchase.payment_status == SoftwarePaymentStatus.CANCELLED:
            return {"success": True, "message": "Purchase already cancelled."}
        if purchase.payment_status != SoftwarePaymentStatus.CREATED:
            raise AppException(
                "Only unpaid purchases can be cancelled. Request a refund after payment.",
                status_code=400,
            )
        purchase.payment_status = SoftwarePaymentStatus.CANCELLED
        await self._purchase_repo.save(purchase)
        await self._session.commit()
        return {"success": True, "message": "Purchase cancelled."}

    async def admin_refund(
        self,
        purchase_id: uuid.UUID,
        *,
        admin: AppUser,
        note: str | None = None,
    ) -> dict[str, Any]:
        del note
        purchase = await self._purchase_repo.get_by_id_for_update(purchase_id)
        if purchase is None:
            raise AppException("Software purchase transaction not found.", status_code=404)
        if purchase.payment_status == SoftwarePaymentStatus.REFUNDED:
            return {
                "success": True,
                "alreadyRefunded": True,
                "refundId": purchase.razorpay_refund_id,
                "refundAmountInr": float(purchase.gross_amount_inr or 0) * 1.18,
            }
        if purchase.seller_paid_at:
            raise AppException(
                "Escrow already released (seller paid). Cannot refund.",
                status_code=400,
            )
        if purchase.payment_status != SoftwarePaymentStatus.COMPLETED:
            raise AppException("Only completed payments can be refunded.", status_code=400)
        if not purchase.razorpay_payment_id:
            raise AppException("No payment to refund.", status_code=400)

        amount = round(float(purchase.gross_amount_inr or 0) * 1.18, 2)
        try:
            refund = rzp.refund_payment(purchase.razorpay_payment_id, amount)
        except rzp.AlreadyFullyRefunded as exc:
            now = datetime.now(timezone.utc)
            purchase.payment_status = SoftwarePaymentStatus.REFUNDED
            purchase.razorpay_refund_id = exc.refund_id
            purchase.refund_completed_at = now
            await self._purchase_repo.save(purchase)
            await self._restore_listing_if_exclusive(purchase)
            await self._session.commit()
            return {
                "success": True,
                "alreadyRefunded": True,
                "refundId": exc.refund_id,
                "refundAmountInr": amount,
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("technology.refund.failed purchase=%s", purchase.id)
            raise AppException(f"Razorpay refund failed: {exc}", status_code=502) from exc

        refund_id = refund.get("id")
        now = datetime.now(timezone.utc)
        purchase.payment_status = SoftwarePaymentStatus.REFUNDED
        purchase.razorpay_refund_id = refund_id
        purchase.refund_completed_at = now
        await self._purchase_repo.save(purchase)
        await self._restore_listing_if_exclusive(purchase)
        await self._session.commit()
        logger.info(
            "technology.refund.completed purchase=%s admin=%s refund_id=%s",
            purchase.id,
            admin.id,
            refund_id,
        )
        return {
            "success": True,
            "refundId": refund_id,
            "refundAmountInr": amount,
        }

    async def confirm_purchase(
        self,
        purchase_id: uuid.UUID,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        """Buyer confirms the software works; unlocks GitHub access."""
        purchase = await self._purchase_repo.get_by_id(purchase_id)
        if purchase is None:
            raise AppException("Purchase not found.", status_code=404)
        if purchase.buyer_id != buyer.id:
            raise AppException("You can only confirm your own purchases.", status_code=403)
        if purchase.payment_status != SoftwarePaymentStatus.COMPLETED:
            raise AppException(
                "Payment must be completed before you can confirm delivery.",
                status_code=400,
            )

        software = purchase.software
        if software is None:
            software = await self._software_repo.get_by_id(purchase.software_id)

        if purchase.completion_status == SoftwarePurchaseCompletionStatus.CONFIRMED:
            github_link = buyer_delivery_github(purchase, software)
            return {
                "success": True,
                "message": "Purchase already confirmed.",
                "githubLink": github_link or "",
                "completionStatus": SoftwarePurchaseCompletionStatus.CONFIRMED.value,
                "purchaseId": str(purchase.id),
            }

        purchase.completion_status = SoftwarePurchaseCompletionStatus.CONFIRMED
        snapshot_delivery(purchase, software)
        await self._purchase_repo.save(purchase)
        await self._session.commit()

        github_link = buyer_delivery_github(purchase, software)
        await self._send_confirmed_email(purchase, software, github_link or "")

        return {
            "success": True,
            "message": "Purchase confirmed successfully.",
            "githubLink": github_link or "",
            "completionStatus": SoftwarePurchaseCompletionStatus.CONFIRMED.value,
            "purchaseId": str(purchase.id),
        }

    @staticmethod
    def _dashboard_url() -> str:
        return f"{settings.FRONTEND_BASE_URL.rstrip('/')}/technology/dashboard"

    async def _send_receipt_email(self, purchase: SoftwarePurchase, software) -> None:
        email = (purchase.buyer_email or "").strip()
        if not email:
            return

        try:
            await MailService.send_software_purchase_receipt_email(
                to_email=email,
                software_name=software.name if software else "Software",
                dashboard_url=self._dashboard_url(),
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "mail.software_purchase_receipt.failed purchase=%s",
                purchase.id,
            )

    async def _send_seller_sold_notification_email(self, purchase: SoftwarePurchase, software) -> None:
        if not software:
            return
            
        seller = software.listed_by
        if not seller and software.listed_by_user_id:
            from sqlalchemy import select
            from app.entity.user.app_user import AppUser
            seller = (await self._session.execute(select(AppUser).where(AppUser.id == software.listed_by_user_id))).scalar_one_or_none()
            
        if not seller:
            return
            
        email = (seller.email or "").strip()
        if not email:
            return

        seller_name = f"{seller.firstname or ''} {seller.lastname or ''}".strip()
        if not seller_name:
            seller_name = email

        try:
            logger.info("Sending software sold seller notification to %s for purchase %s", email, purchase.id)
            await MailService.send_software_sold_seller_notification_email(
                to_email=email,
                seller_name=seller_name,
                software_name=software.name or "Software",
                buyer_name=purchase.buyer_full_name or "A buyer",
                price=float(purchase.gross_amount_inr or 0),
                dashboard_url=self._dashboard_url(),
            )
            logger.info("Successfully sent seller notification for purchase %s", purchase.id)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "mail.software_sold_seller_notification.failed purchase=%s error=%s",
                purchase.id,
                str(exc),
            )

    async def _send_confirmed_email(
        self,
        purchase: SoftwarePurchase,
        software,
        github_link: str,
    ) -> None:
        email = (purchase.buyer_email or "").strip()
        if not email or not github_link:
            return
        try:
            await MailService.send_software_purchase_confirmed_email(
                to_email=email,
                software_name=software.name if software else "Software",
                github_link=github_link,
                dashboard_url=self._dashboard_url(),
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "mail.software_purchase_confirmed.failed purchase=%s",
                purchase.id,
            )

    async def _create_cobrother_request(self, purchase: SoftwarePurchase, software) -> None:
        if software is None:
            return
        req = CoBrotherRequest(
            request_type=CoBrotherRequestType.COCREATION,
            entity_id=purchase.id,
            entity_snapshot=software.name,
            lister_id=purchase.buyer_id,
            status=CoBrotherRequestStatus.PENDING,
        )
        await self._cobrother_repo.create(req)

    async def create_cobrother_help_order(
        self,
        purchase_id: uuid.UUID,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        purchase = await self._purchase_repo.get_by_id(purchase_id)
        if purchase is None:
            raise AppException("Purchase not found.", status_code=404)
        if purchase.buyer_id != buyer.id:
            raise AppException("Forbidden.", status_code=403)
        if purchase.payment_status != SoftwarePaymentStatus.COMPLETED:
            raise AppException("Purchase is not completed.", status_code=400)
        if purchase.co_brother_opt_in:
            raise AppException("HubRegistrar help was included in checkout.", status_code=400)
        if purchase.co_brother_help_paid:
            raise AppException("HubRegistrar help already paid.", status_code=409)
        if purchase.cobrother_help_razorpay_order_id:
            raise AppException("Payment order already created.", status_code=409)
        if not rzp.is_configured():
            raise AppException("Payment gateway is not configured.", status_code=503)
        receipt = f"cbrhelp_{str(purchase_id).replace('-', '')[:12]}"
        try:
            order = rzp.create_order(
                amount_inr=self.COBROTHER_FEE_INR,
                receipt=receipt,
                notes={"purchaseId": str(purchase_id)},
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("cobrother_help.create_order.failed purchase=%s", purchase_id)
            raise AppException("Could not create payment order.", status_code=502) from exc
        purchase.cobrother_help_razorpay_order_id = order["id"]
        await self._purchase_repo.save(purchase)
        await self._session.commit()
        return {
            "orderId": order["id"],
            "amount": self.COBROTHER_FEE_INR,
            "currency": "INR",
            "keyId": rzp.get_key_id(),
        }

    async def verify_cobrother_help(
        self,
        purchase_id: uuid.UUID,
        *,
        razorpay_payment_id: str,
        razorpay_order_id: str,
        razorpay_signature: str,
        buyer: AppUser,
    ) -> dict[str, Any]:
        purchase = await self._purchase_repo.get_by_id(purchase_id)
        if purchase is None:
            raise AppException("Purchase not found.", status_code=404)
        if purchase.buyer_id != buyer.id:
            raise AppException("Forbidden.", status_code=403)
        if not purchase.cobrother_help_razorpay_order_id:
            raise AppException("No pending HubRegistrar help order.", status_code=400)
        if purchase.cobrother_help_razorpay_order_id != razorpay_order_id:
            raise AppException("Order id mismatch.", status_code=400)
        if not rzp.verify_payment_signature(razorpay_order_id, razorpay_payment_id, razorpay_signature):
            raise AppException("Verification failed.", status_code=400)
        purchase.co_brother_help_paid = True
        await self._purchase_repo.save(purchase)
        await self._session.commit()
        return {"success": True, "message": "HubRegistrar help payment verified"}
