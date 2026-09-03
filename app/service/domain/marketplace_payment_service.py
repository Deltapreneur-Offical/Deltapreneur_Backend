"""Razorpay purchase flow for domain marketplace listings."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)
from app.entity.cobranding.domain_listing_entity import DomainListing
from app.entity.user.app_user import AppUser
from app.integrations.razorpay import client as rzp
from app.repository.domain_listing_repository import DomainListingRepository
from app.repository.domain_marketplace_transaction_repository import (
    DomainMarketplaceTransactionRepository,
)
from app.service.domain.domain_marketplace_transaction_service import (
    DomainMarketplaceTransactionService,
)
from app.service.domain.domain_transfer_notification_service import (
    DomainTransferNotificationService,
)
from app.utils.addon_services import resolve_buyer_phone
from app.utils.marketplace_enums import DomainListingStatus, MarketplacePaymentStatus
from app.service.currency.exchange_rate_service import convert_inr


class MarketplacePaymentService:
    COBROTHER_HELP_FEE = 1000.0

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DomainListingRepository(session)

    async def create_purchase_order(
        self,
        listing_id: uuid.UUID,
        *,
        buyer: AppUser,
        buyer_name: str = "",
        buyer_email: str = "",
        buyer_phone: str = "",
        addon_amount: float = 0.0,
        selected_addon_services: str = "",
        currency: str = "INR",
        redeem_points: bool = False,
    ) -> dict[str, Any]:
        if not rzp.is_configured():
            raise AppException(
                "Payment gateway is not configured.",
                status_code=503,
            )

        listing = await self._repo.get_by_id(listing_id)
        if listing is None:
            raise AppException("Domain listing not found.", status_code=404)
        if listing.listed_by_user_id == buyer.id:
            raise AppException("You cannot buy your own domain.", status_code=400)
            # If you uncomment the below code, it will require domain verification before purchase,
            #  This is currently disabled because we are not verifying domains yet:

        #    if settings.REQUIRE_DOMAIN_VERIFICATION_BEFORE_PURCHASE and not listing.verified:
        #     raise AppException(
        #         "This domain is not verified by the owner yet.",
        #         status_code=400,
        #     )

        if listing.domain_status == DomainListingStatus.SOLD:
            raise AppException("This domain has already been sold.", status_code=409)

        if listing.domain_status == DomainListingStatus.UNDER_REVIEW:
            raise AppException(
                "This domain is currently under review for premium acquisition.",
                status_code=409,
            )

        if listing.domain_status == DomainListingStatus.PENDING:
            if listing.purchased_by_user_id != buyer.id:
                raise AppException(
                    "Another buyer is completing payment for this domain.",
                    status_code=409,
                )
        elif listing.domain_status != DomainListingStatus.AVAILABLE:
            raise AppException("Domain is not available for purchase.", status_code=400)

        domain_price = float(listing.asking_price or 0)
        # Marketplace premiums (> ₹5L) use enquiry cart confirm — never Razorpay buy-now.
        from app.service.domain.domain_enquiry_service import (
            PREMIUM_MARKETPLACE_MIN_PRICE_INR,
            is_premium_marketplace_listing,
        )

        if is_premium_marketplace_listing(listing) or domain_price > PREMIUM_MARKETPLACE_MIN_PRICE_INR:
            raise AppException(
                "Premium marketplace domains cannot be purchased online. "
                "Add to cart and submit an acquisition request.",
                status_code=400,
            )
        sub_total = domain_price + addon_amount
        from app.utils.domain_gst import domain_price_breakdown

        pricing = domain_price_breakdown(sub_total, years=1)
        order_amount = float(pricing["totalInr"])

        # Convert price and fees if currency is not INR
        if currency and currency.upper() != "INR":
            try:
                conversion = convert_inr(order_amount, currency)
                amount_to_charge = conversion["converted"]
                currency_code = currency.upper()
                domain_price_conv = convert_inr(domain_price, currency)["converted"]
                addon_amount_conv = convert_inr(addon_amount, currency)["converted"]
            except Exception:
                amount_to_charge = order_amount
                currency_code = "INR"
                domain_price_conv = domain_price
                addon_amount_conv = addon_amount
        else:
            amount_to_charge = order_amount
            currency_code = "INR"
            domain_price_conv = domain_price
            addon_amount_conv = addon_amount

        phone = resolve_buyer_phone(buyer_phone, buyer)

        listing.purchase_buyer_name = (buyer_name or "").strip() or None
        listing.purchase_buyer_email = (buyer_email or buyer.email or "").strip() or None
        listing.purchase_buyer_phone = phone
        listing.purchase_addon_services = (selected_addon_services or "").strip() or None

        contact_only = bool(selected_addon_services) and addon_amount <= 0 and domain_price <= 0
        if order_amount <= 0 and not contact_only:
            raise AppException("Invalid listing price for payment.", status_code=400)

        if contact_only:
            listing.domain_status = DomainListingStatus.SOLD
            listing.payment_status = MarketplacePaymentStatus.CONTACT_PENDING
            listing.purchased_by_user_id = buyer.id
            listing.sold_at = datetime.now(timezone.utc)
            await self._repo.save(listing)

            # Create Operations requests for selected compliance addons
            from app.utils.addon_services import create_addon_operations_requests
            buyer_phone = listing.purchase_buyer_phone or (buyer.phone_number if buyer else "")
            buyer_email = listing.purchase_buyer_email or (buyer.email if buyer else "")
            buyer_name = listing.purchase_buyer_name or (
                " ".join(p for p in (buyer.firstname, buyer.lastname) if p).strip() if buyer else ""
            )
            await create_addon_operations_requests(
                self._session,
                user_id=buyer.id,
                buyer_name=buyer_name,
                buyer_email=buyer_email,
                buyer_phone=buyer_phone,
                addon_services_csv=listing.purchase_addon_services,
            )

            await self._session.commit()
            return {
                "orderId": None,
                "amount": 0,
                "domainPrice": 0,
                "addonAmount": 0,
                "currency": currency_code,
                "domainId": str(listing_id),
                "contactOnly": True,
                "paymentStatus": "CONTACT_PENDING",
            }

        points_redeemed = 0
        if currency_code == "INR" and amount_to_charge > 0:
            from app.service.user.edge_points_service import EdgePointsService
            amount_to_charge, points_redeemed = await EdgePointsService.calculate_redemption(
                self._session, buyer, amount_to_charge, redeem_points
            )

        receipt = f"dl_{str(listing_id).replace('-', '')[:20]}"
        try:
            rzp_order = rzp.create_order(
                amount_inr=amount_to_charge,
                currency=currency_code,
                receipt=receipt,
                notes={"domainListingId": str(listing_id), "buyerId": str(buyer.id)},
            )
            if points_redeemed > 0:
                from app.service.user.edge_points_service import EdgePointsService
                await EdgePointsService.create_pending_redemption(
                    self._session, buyer.id, rzp_order["id"], points_redeemed
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "razorpay.create_order.failed listing=%s buyer=%s",
                listing_id,
                buyer.id,
            )
            detail = str(exc)
            if isinstance(exc, ValueError) and detail:
                raise AppException(detail, status_code=400) from exc
            lower = detail.lower()
            if "maximum amount" in lower or "amount exceeds" in lower:
                raise AppException(
                    "This purchase amount exceeds the payment gateway limit for instant checkout. "
                    "Please use Add to Cart or contact support for assisted purchase.",
                    status_code=400,
                ) from exc
            raise AppException(
                "Could not create payment order. Please try again.",
                status_code=502,
            ) from exc

        listing.domain_status = DomainListingStatus.PENDING
        listing.razorpay_order_id = rzp_order["id"]
        listing.payment_status = MarketplacePaymentStatus.CREATED
        listing.purchased_by_user_id = buyer.id
        await self._repo.save(listing)
        await self._session.commit()

        return {
            "orderId": rzp_order["id"],
            "amount": amount_to_charge,
            "domainPrice": domain_price_conv,
            "addonAmount": addon_amount_conv,
            "currency": currency_code,
            "domainId": str(listing_id),
            "keyId": rzp.get_key_id(),
        }

    async def verify_payment(
        self,
        listing_id: uuid.UUID,
        *,
        razorpay_payment_id: str,
        razorpay_order_id: str,
        razorpay_signature: str,
        buyer: AppUser,
    ) -> dict[str, Any]:
        tx_repo = DomainMarketplaceTransactionRepository(self._session)
        existing = await tx_repo.get_by_razorpay_payment_id(razorpay_payment_id)
        if existing is not None:
            from app.service.platform.track_record_service import TrackRecordService

            track_service = TrackRecordService(self._session)
            await track_service.backfill_from_registration_orders(
                razorpay_order_id=razorpay_order_id,
                razorpay_payment_id=razorpay_payment_id,
            )
            await self._session.commit()
            return {
                "success": True,
                "message": "Payment successful",
                "domainId": str(listing_id),
                "transactionId": str(existing.id),
                "transferStatus": existing.transfer_status.value,
            }

        listing = await self._repo.get_by_id_for_update(listing_id)
        if listing is None:
            raise AppException("Domain listing not found.", status_code=404)
        if (
            listing.purchased_by_user_id is not None
            and listing.purchased_by_user_id != buyer.id
        ):
            raise AppException(
                "This purchase order belongs to another user.",
                status_code=403,
            )

        from app.service.platform.track_record_service import (
            TrackRecordService,
            TrackRecordCategory,
            PaymentStatus,
            FulfillmentStatus,
            OverallStatus,
        )
        track_service = TrackRecordService(self._session)

        if not rzp.verify_payment_signature(
            razorpay_order_id, razorpay_payment_id, razorpay_signature,
        ):
            from app.service.user.edge_points_service import EdgePointsService
            await EdgePointsService.cancel_redemption(self._session, razorpay_order_id)
            listing.domain_status = DomainListingStatus.AVAILABLE
            listing.payment_status = MarketplacePaymentStatus.FAILED
            listing.purchased_by_user_id = None
            listing.razorpay_order_id = None
            await self._repo.save(listing)

            await track_service.record_paid_attempt(
                internal_order_id=f"TRK-MKT-{razorpay_order_id}",
                category=TrackRecordCategory.DOMAIN_MARKETPLACE,
                provider_subcategory="Razorpay",
                item_name=listing.domain_name or str(listing_id),
                item_id=str(listing_id),
                buyer_name=listing.purchase_buyer_name or (buyer.full_name if buyer else ""),
                buyer_email=listing.purchase_buyer_email or (buyer.email if buyer else ""),
                buyer_phone=listing.purchase_buyer_phone or (buyer.mobile_number if buyer else ""),
                buyer_user_id=buyer.id if buyer else None,
                amount_charged=float(listing.asking_price or 0.0),
                currency="INR",
                payment_status=PaymentStatus.FAILED,
                razorpay_order_id=razorpay_order_id,
                razorpay_payment_id=razorpay_payment_id,
                fulfillment_status=FulfillmentStatus.FAILED,
                overall_status=OverallStatus.FAILED,
                error_code="SIGNATURE_VERIFICATION_FAILED",
                error_message="Razorpay payment signature verification failed",
                error_source="RAZORPAY",
            )

            await self._session.commit()
            raise AppException("Payment verification failed.", status_code=400)

        listing.domain_status = DomainListingStatus.SOLD
        listing.payment_status = MarketplacePaymentStatus.COMPLETED
        listing.razorpay_payment_id = razorpay_payment_id
        listing.purchased_by_user_id = buyer.id
        listing.sold_at = datetime.now(timezone.utc)
        await self._repo.save(listing)
        from app.service.user.edge_points_service import EdgePointsService
        await EdgePointsService.confirm_redemption(self._session, razorpay_order_id)

        # Create Operations requests for selected compliance addons
        from app.utils.addon_services import create_addon_operations_requests
        buyer_phone = listing.purchase_buyer_phone or (buyer.phone_number if buyer else "")
        buyer_email = listing.purchase_buyer_email or (buyer.email if buyer else "")
        buyer_name = listing.purchase_buyer_name or (
            " ".join(p for p in (buyer.firstname, buyer.lastname) if p).strip() if buyer else ""
        )
        await create_addon_operations_requests(
            self._session,
            user_id=buyer.id,
            buyer_name=buyer_name,
            buyer_email=buyer_email,
            buyer_phone=buyer_phone,
            addon_services_csv=listing.purchase_addon_services,
        )

        tx_service = DomainMarketplaceTransactionService(self._session)
        notify = DomainTransferNotificationService(self._session)
        try:
            tx = await tx_service.create_from_payment(
                listing,
                buyer=buyer,
                razorpay_order_id=razorpay_order_id,
                razorpay_payment_id=razorpay_payment_id,
            )
            await notify.on_payment_completed(tx)
            from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
            from app.utils.registration_enums import RegistrationOrderStatus

            domain_full = str(listing.domain_name or "").strip().lower()
            if "." in domain_full:
                name_part, ext_part = domain_full.split(".", 1)
                ext_full = "." + ext_part
            else:
                name_part, ext_full = domain_full, ".com"

            asking_price = float(listing.asking_price or 0.0)
            from app.utils.domain_gst import domain_price_breakdown

            listing_tax = domain_price_breakdown(asking_price, years=1)
            domain_order = DomainRegistrationOrder(
                domain_name=name_part,
                domain_extension=ext_full,
                buyer_id=buyer.id if buyer else None,
                buyer_full_name=buyer_name or (buyer.full_name if buyer else "") or buyer_email,
                buyer_email=buyer_email or (buyer.email if buyer else ""),
                buyer_phone=buyer_phone or (buyer.mobile_number if buyer else ""),
                street="Main Street",
                city="Hubli",
                state="Karnataka",
                zip_code="580001",
                country="IN",
                period_years=1,
                subtotal_inr=float(listing_tax["subtotalInr"]),
                gst_inr=float(listing_tax["gstInr"]),
                price_inr=float(listing_tax["totalInr"]),
                quoted_unit_price_inr=asking_price,
                price_source="marketplace",
                status=RegistrationOrderStatus.ACTIVE,
                razorpay_order_id=razorpay_order_id,
                razorpay_payment_id=razorpay_payment_id,
                provision_message="Direct marketplace domain purchase completed.",
                provision_attempts=1,
            )
            self._session.add(domain_order)
            await self._session.flush()
            from app.service.domain.tax_invoice_number_service import ensure_tax_invoice_number

            await ensure_tax_invoice_number(self._session, domain_order)
            await self._session.flush()

            await track_service.record_from_registration_order(
                domain_order,
                cart_batch_id=razorpay_order_id,
                internal_order_id=f"TRK-MKT-{razorpay_order_id}",
            )
            logger.info(
                "marketplace.verify.track_record listing=%s payment=%s order=%s",
                listing_id,
                razorpay_payment_id,
                domain_order.id,
            )
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            replay = await tx_repo.get_by_razorpay_payment_id(razorpay_payment_id)
            if replay is None:
                raise
            return {
                "success": True,
                "message": "Payment successful",
                "domainId": str(listing_id),
                "transactionId": str(replay.id),
                "transferStatus": replay.transfer_status.value,
            }

        return {
            "success": True,
            "message": "Payment successful",
            "domainId": str(listing_id),
            "transactionId": str(tx.id),
            "transferStatus": tx.transfer_status.value,
        }

    async def handle_payment_failure(
        self,
        listing_id: uuid.UUID,
    ) -> dict[str, Any]:
        listing = await self._repo.get_by_id(listing_id)
        if listing is None:
            raise AppException("Domain listing not found.", status_code=404)

        if listing.razorpay_order_id:
            from app.service.user.edge_points_service import EdgePointsService
            await EdgePointsService.cancel_redemption(self._session, listing.razorpay_order_id)

        listing.domain_status = DomainListingStatus.AVAILABLE
        listing.payment_status = MarketplacePaymentStatus.FAILED
        listing.purchased_by_user_id = None
        listing.razorpay_order_id = None
        await self._repo.save(listing)
        await self._session.commit()
        return {"success": False}
