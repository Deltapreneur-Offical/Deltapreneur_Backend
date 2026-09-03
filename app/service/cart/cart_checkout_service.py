"""Cart checkout orchestrator — creates a combined Razorpay order and
delegates post-payment processing to existing module-specific services."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.exc import PendingRollbackError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.entity.cart.cart_item_entity import CartItem
from app.entity.cocreation.software_purchase_entity import SoftwarePurchase
from app.entity.cobrother.cobrother_request_entity import CoBrotherRequest
from app.entity.user.app_user import AppUser
from app.integrations.razorpay import client as rzp
from app.repository.cart_item_repository import CartItemRepository
from app.schemas.cart_schemas import CartCheckoutResponse, CartVerifyRequest
from app.service.cart.cart_service import CartService
from app.service.currency.exchange_rate_service import convert_inr, SUPPORTED_CURRENCIES as FX_SUPPORTED
from app.service.resellportal.product_mapper import (
    build_order_parameters,
    get_product_key,
    is_provider_mapped,
    validate_order_input,
)
from app.utils.addon_services import ADDON_PRICES, create_addon_operations_requests
from app.utils.cart_enums import CartProductType
from app.utils.cocreation_enums import (
    SoftwarePaymentStatus,
    SoftwarePurchaseCompletionStatus,
    SoftwarePurchaseType,
    SoftwareStatus,
    TechnologyPricingPlanDuration,
    TechnologyType,
)
from app.utils.marketplace_enums import (
    CoBrotherRequestStatus,
    CoBrotherRequestType,
    DomainListingStatus,
    MarketplacePaymentStatus,
)

logger = logging.getLogger(__name__)


async def _reset_aborted_session(session: AsyncSession) -> None:
    """Clear a failed SQLAlchemy transaction so later reads/commits can proceed.

    Concurrent webhook vs browser-verify can abort the session (e.g. cart_items
    DELETE matching 0 rows after the other path already removed them). Without
    rollback, the next statement raises PendingRollbackError and a captured
    payment is reported as verification failure.
    """
    try:
        await session.rollback()
    except Exception:
        logger.debug("cart.checkout.aborted_session_rollback_skipped", exc_info=True)


COBROTHER_FEE_INR = 1000.0

# Razorpay notes: max 15 keys; each value should stay well under 256 chars.
_RZP_NOTE_MAX = 240

_CART_CATEGORY_LABELS: dict[CartProductType, str] = {
    CartProductType.DOMAIN_REGISTRATION: "Domain Registration",
    CartProductType.DOMAIN_LISTING: "Domain Marketplace",
    CartProductType.TECHNOLOGY: "Technology",
    CartProductType.VENTURE_DEAL: "Venture",
}


def _rzp_note(value: Any, *, max_len: int = _RZP_NOTE_MAX) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _cart_item_category_label(item: CartItem) -> str:
    product_type = item.product_type
    if isinstance(product_type, CartProductType):
        return _CART_CATEGORY_LABELS.get(product_type, product_type.value)
    try:
        enum_type = CartProductType(str(product_type))
        return _CART_CATEGORY_LABELS.get(enum_type, enum_type.value)
    except ValueError:
        raw = str(product_type or "Other").strip()
        return raw.replace("_", " ").title() or "Other"


def _cart_item_product_name(item: CartItem) -> str:
    """Product title only (no category) — metadata only, no extra DB reads."""
    meta = item.metadata_json or {}
    product_type = item.product_type
    if product_type == CartProductType.DOMAIN_REGISTRATION:
        return str(meta.get("domainName") or "Domain registration").strip()
    if product_type == CartProductType.DOMAIN_LISTING:
        return str(
            meta.get("domainName")
            or meta.get("fullDomain")
            or meta.get("productName")
            or "Domain listing"
        ).strip()
    if product_type == CartProductType.TECHNOLOGY:
        return str(
            meta.get("productName")
            or meta.get("softwareName")
            or meta.get("name")
            or "Technology"
        ).strip()
    if product_type == CartProductType.VENTURE_DEAL:
        return str(
            meta.get("productName")
            or meta.get("ventureName")
            or meta.get("name")
            or "Venture"
        ).strip()
    return str(getattr(product_type, "value", product_type) or "Item").strip()


def _checkout_buyer_details(item: CartItem, buyer: AppUser) -> dict[str, str]:
    """Buyer fields for Track Records — prefer checkout stamp, then registrant, then user."""
    meta = item.metadata_json or {}
    name = str(meta.get("_checkout_buyer_name") or buyer.full_name or buyer.username or "").strip()
    email = str(meta.get("_checkout_buyer_email") or buyer.email or "").strip()
    phone = str(meta.get("_checkout_buyer_phone") or buyer.phone_number or "").strip()

    if item.product_type == CartProductType.DOMAIN_REGISTRATION:
        registrant = meta.get("_checkout_registrant") or {}
        if isinstance(registrant, dict):
            reg_name = (
                f"{registrant.get('firstName', '')} {registrant.get('lastName', '')}".strip()
            )
            if reg_name:
                name = reg_name
            if registrant.get("email"):
                email = str(registrant.get("email")).strip()
            if registrant.get("phone"):
                phone = str(registrant.get("phone")).strip()

    return {"name": name, "email": email, "phone": phone}


def _track_internal_order_id(
    *,
    razorpay_order_id: str,
    item: CartItem,
    result: dict[str, Any] | None = None,
) -> str:
    reg_order_id = (result or {}).get("registrationOrderId")
    if reg_order_id:
        return f"TRK-REG-{reg_order_id}"
    if item.product_type == CartProductType.DOMAIN_LISTING:
        return f"TRK-MKT-{razorpay_order_id}-{item.id}"
    return f"TRK-{razorpay_order_id}-{item.id}"


def _fulfillment_from_provision_result(result: dict[str, Any]) -> tuple[str, str, str | None, str | None]:
    from app.service.platform.track_record_service import (
        FulfillmentStatus,
        OverallStatus,
    )

    status = str(result.get("status") or "").upper()
    if result.get("success") is False or "FAIL" in status:
        return (
            FulfillmentStatus.FAILED,
            OverallStatus.FAILED,
            "PROVISIONING_ERROR",
            str(result.get("error") or result.get("message") or "Provisioning failed"),
        )
    if status in ("ACTIVE", "REGISTERED"):
        return FulfillmentStatus.PROVISIONED, OverallStatus.SUCCESS, None, None
    return FulfillmentStatus.IN_PROGRESS, OverallStatus.PENDING, None, None


def _tech_fulfillment_from_result(
    result: dict[str, Any],
    is_service: bool = True,
) -> tuple[str, str, str | None, str | None]:
    """Technology fulfillment state.

    One-time software products are fulfilled on payment capture. Provider-
    powered services follow their actual subscription/provisioning state
    (ACTIVE + provider subscription id => provisioned, PENDING => in progress,
    FAIL => failed). A technology transaction must never inherit a
    domain-registration status.
    """
    from app.service.platform.track_record_service import (
        FulfillmentStatus,
        OverallStatus,
    )

    if not is_service:
        return FulfillmentStatus.PROVISIONED, OverallStatus.SUCCESS, None, None
    sub_status = str(result.get("status") or "").upper()
    # PROVISIONED/SUCCESS is only valid when the provider confirmed the
    # subscription: status ACTIVE AND a provider subscription id exists.
    if sub_status == "ACTIVE" and result.get("providerSubscriptionId"):
        return FulfillmentStatus.PROVISIONED, OverallStatus.SUCCESS, None, None
    if sub_status in ("PENDING", "PAYMENT_CAPTURED", "PROVISIONING", "PROVISIONING_PENDING"):
        return FulfillmentStatus.IN_PROGRESS, OverallStatus.PENDING, None, None
    return (
        FulfillmentStatus.FAILED,
        OverallStatus.FAILED,
        "SERVICE_PROVISIONING_FAILED",
        str(
            result.get("error")
            or result.get("message")
            or f"Provider subscription status: {sub_status or 'UNKNOWN'}"
        ),
    )


# Retry backoff between automatic provisioning attempts (minutes) — mirrors
# the retry worker's schedule so checkout and retries behave consistently.
_TECH_RETRY_BACKOFF_MINUTES = (5, 15, 60, 360, 1440)


def _tech_sub_periods(billing_cycle: str) -> tuple[datetime, datetime]:
    """Default period window for a subscription (renewable services)."""
    now = datetime.now(timezone.utc)
    days = 365 if str(billing_cycle or "").lower().startswith("ann") else 30
    return now, now + timedelta(days=days)


def _tech_backoff_for(attempt_number: int) -> timedelta:
    """Backoff after ``attempt_number`` attempts (1-based)."""
    idx = min(max(attempt_number - 1, 0), len(_TECH_RETRY_BACKOFF_MINUTES) - 1)
    return timedelta(minutes=_TECH_RETRY_BACKOFF_MINUTES[idx])


def _cart_item_payment_label(item: CartItem) -> str:
    """Category + name, e.g. 'Domain Registration: example.com'."""
    category = _cart_item_category_label(item)
    name = _cart_item_product_name(item)[:72]
    if not name:
        return category
    return f"{category}: {name}"


def _summarize_cart_categories_for_razorpay(items: list[CartItem]) -> str:
    seen: list[str] = []
    for it in items:
        label = _cart_item_category_label(it)
        if label and label not in seen:
            seen.append(label)
    return _rzp_note(", ".join(seen) if seen else "Cart")


def _summarize_cart_items_for_razorpay(items: list[CartItem]) -> str:
    labels = [_cart_item_payment_label(it)[:90] for it in items[:4]]
    text = " | ".join(label for label in labels if label)
    extra = len(items) - len(labels)
    if extra > 0:
        text = f"{text} (+{extra} more)" if text else f"{extra} items"
    return _rzp_note(text or f"{len(items)} item(s)")


def _build_cart_payment_description(items: list[CartItem]) -> str:
    categories = _summarize_cart_categories_for_razorpay(items)
    summary = _summarize_cart_items_for_razorpay(items)
    if summary:
        # Prefer category-first description for ops scanning Razorpay dashboard.
        return _rzp_note(f"HubRegistrar - {categories} - {summary}")
    count = len(items)
    return f"HubRegistrar Cart ({count} item{'s' if count != 1 else ''})"


class CartCheckoutService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = CartItemRepository(session)
        self._cart_service = CartService(session)

    async def remove_fulfilled_cart_items_for_payment(
        self,
        buyer_id: uuid.UUID,
        *,
        razorpay_order_id: str,
        domains: list[str] | None = None,
    ) -> int:
        """Delete cart rows fulfilled by a captured Razorpay payment.

        Safe / idempotent: only removes the buyer's own cart_items rows that
        still match this Razorpay order metadata or a successful domain FQDN.
        Does not touch registration orders, listings, or any other tables.
        """
        order_id = str(razorpay_order_id or "").strip()
        if not order_id or not buyer_id:
            return 0

        try:
            items = await self._repo.get_by_user(buyer_id)
        except PendingRollbackError:
            logger.warning(
                "cart.checkout.cart_cleanup.pending_rollback buyer=%s order=%s",
                buyer_id,
                order_id,
            )
            await _reset_aborted_session(self._session)
            try:
                items = await self._repo.get_by_user(buyer_id)
            except Exception:
                logger.exception(
                    "cart.checkout.cart_cleanup.reread_failed buyer=%s order=%s",
                    buyer_id,
                    order_id,
                )
                return 0

        domain_set = {
            str(d).lower().strip()
            for d in (domains or [])
            if str(d or "").strip()
        }
        to_delete: list[uuid.UUID] = []
        for item in items:
            meta = item.metadata_json or {}
            if meta.get("_checkout_razorpay_order_id") == order_id:
                to_delete.append(item.id)
                continue
            if (
                item.product_type == CartProductType.DOMAIN_REGISTRATION
                and domain_set
            ):
                dn = str(meta.get("domainName") or "").lower().strip()
                if dn and dn in domain_set:
                    to_delete.append(item.id)

        if not to_delete:
            return 0

        try:
            deleted = await self._repo.delete_items_by_ids(to_delete, buyer_id)
        except PendingRollbackError:
            logger.warning(
                "cart.checkout.cart_cleanup.delete_pending_rollback buyer=%s order=%s",
                buyer_id,
                order_id,
            )
            await _reset_aborted_session(self._session)
            return 0
        logger.info(
            "[CART_CLEANUP] Removed %s cart item(s) for buyer=%s razorpay_order_id=%s domains=%s",
            deleted,
            buyer_id,
            order_id,
            sorted(domain_set) if domain_set else [],
        )
        return deleted


    async def create_checkout_order(
        self,
        buyer: AppUser,
        *,
        redeem_points: bool = False,
        currency: str = "INR",
        buyer_name: str = "",
        buyer_email: str = "",
        buyer_phone: str = "",
        registrant: dict[str, Any] | None = None,
        period_years: int | None = None,
    ) -> dict[str, Any]:
        if not rzp.is_configured():
            raise AppException("Payment gateway is not configured.", status_code=503)

        items = await self._repo.get_by_user(buyer.id)
        if not items:
            raise AppException("Cart is empty.", status_code=400)

        # Premium marketplace (> ₹5L) never goes through Razorpay cart checkout.
        from app.service.domain.domain_enquiry_service import is_premium_marketplace_listing
        from app.repository.domain_listing_repository import DomainListingRepository
        from app.service.domain.managed_acquisition_pricing import (
            is_openprovider_managed_registration,
        )

        listing_repo = DomainListingRepository(self._session)
        for it in items:
            if it.product_type != CartProductType.DOMAIN_LISTING:
                continue
            listing = await listing_repo.get_by_id(it.product_id)
            if listing is not None and is_premium_marketplace_listing(listing):
                raise AppException(
                    "Premium marketplace domains require acquisition confirmation, "
                    "not payment checkout. Use Confirm Request in cart.",
                    status_code=400,
                )

        domain_reg_items = [
            it for it in items if it.product_type == CartProductType.DOMAIN_REGISTRATION
        ]
        if domain_reg_items:
            self._require_registrant(registrant)
            # Each domain keeps its own selected period (metadata.period).
            # Optional legacy period_years is ignored for multi-item correctness.
            _ = period_years
            await self._revalidate_domain_registration_items(domain_reg_items)
            for it in domain_reg_items:
                if is_openprovider_managed_registration(it.metadata_json):
                    raise AppException(
                        "This domain requires managed acquisition confirmation, "
                        "not payment checkout. Use Confirm Request in cart.",
                        status_code=400,
                        code="MANAGED_ACQUISITION_CONFIRM",
                    )

        total_amount = 0.0
        valid_items: list[CartItem] = []
        line_totals: dict[uuid.UUID, float] = {}

        for item in items:
            line = await self._resolve_line_total(item, buyer)
            if line is None:
                continue
            total_amount += line
            valid_items.append(item)
            line_totals[item.id] = line

        if not valid_items:
            raise AppException("No available items in cart.", status_code=400)

        if total_amount <= 0:
            raise AppException("Cart total must be greater than zero.", status_code=400)

        from app.utils.domain_gst import domain_price_breakdown

        pricing = domain_price_breakdown(total_amount, years=1)
        order_amount = float(pricing["totalInr"])

        points_redeemed = 0
        if redeem_points and currency.upper() == "INR" and order_amount > 0:
            from app.service.user.edge_points_service import EdgePointsService

            order_amount, points_redeemed = await EdgePointsService.calculate_redemption(
                self._session, buyer, order_amount, redeem_points
            )

        # Convert INR amount to the requested currency for Razorpay
        order_amount_inr = order_amount
        charge_currency = "INR"
        charge_amount = order_amount
        currency_fallback = False

        if currency.upper() != "INR":
            try:
                conversion = convert_inr(order_amount, currency)
                charge_amount = conversion["converted"]
                charge_currency = currency.upper()
            except Exception as exc:
                logger.warning(
                    "cart.checkout.currency_conversion_failed currency=%s err=%s",
                    currency, exc,
                )
                raise AppException(
                    f"Currency {currency.upper()} is not supported for checkout.",
                    status_code=400,
                ) from exc

        receipt = f"cart_{str(buyer.id).replace('-', '')[:16]}"

        resolved_buyer_name = _rzp_note(
            buyer_name
            or f"{buyer.firstname or ''} {buyer.lastname or ''}".strip()
            or buyer.email
            or "",
            max_len=120,
        )
        resolved_buyer_email = _rzp_note(
            buyer_email or buyer.email or "",
            max_len=120,
        )
        resolved_buyer_phone = _rzp_note(
            buyer_phone or (buyer.phone_number or ""),
            max_len=20,
        )
        items_summary = _summarize_cart_items_for_razorpay(valid_items)
        categories_summary = _summarize_cart_categories_for_razorpay(valid_items)
        payment_description = _build_cart_payment_description(valid_items)

        try:
            rzp_order = rzp.create_order(
                amount_inr=charge_amount,
                receipt=receipt,
                currency=charge_currency,
                notes={
                    "cartCheckout": "true",
                    "buyerId": str(buyer.id),
                    "buyerName": resolved_buyer_name,
                    "buyerEmail": resolved_buyer_email,
                    "buyerPhone": resolved_buyer_phone,
                    "itemCount": str(len(valid_items)),
                    "categories": categories_summary,
                    "items": items_summary,
                    "originalCurrency": currency.upper(),
                    "amountInr": str(order_amount_inr),
                },
            )
        except Exception as exc:
            logger.exception("cart.checkout.razorpay_create_order.failed buyer=%s", buyer.id)
            msg = str(exc)
            if "currency" in msg.lower() or "unsupported" in msg.lower():
                raise AppException(
                    f"Currency {charge_currency} is not supported by the payment gateway.",
                    status_code=400,
                ) from exc
            detail = str(exc)
            if isinstance(exc, ValueError) and detail:
                raise AppException(detail, status_code=400) from exc
            raise AppException(
                "Could not create payment order. Please try again.",
                status_code=502,
            ) from exc

        if points_redeemed > 0:
            from app.service.user.edge_points_service import EdgePointsService

            await EdgePointsService.create_pending_redemption(
                self._session, buyer.id, rzp_order["id"], points_redeemed
            )

        batch_id = str(uuid.uuid4()) if domain_reg_items else None
        for item in valid_items:
            item.metadata_json = item.metadata_json or {}
            item.metadata_json["_checkout_razorpay_order_id"] = rzp_order["id"]
            item.metadata_json["_checkout_buyer_name"] = resolved_buyer_name
            item.metadata_json["_checkout_buyer_email"] = resolved_buyer_email
            item.metadata_json["_checkout_buyer_phone"] = resolved_buyer_phone
            item.metadata_json["_checkout_payment_currency"] = charge_currency
            item.metadata_json["_checkout_unit_price_inr"] = float(line_totals.get(item.id, 0.0))
            if item.product_type == CartProductType.DOMAIN_LISTING:
                from app.utils.domain_gst import domain_price_breakdown

                line_ex_gst = float(line_totals.get(item.id, 0.0))
                listing_tax = domain_price_breakdown(line_ex_gst, years=1)
                item.metadata_json["_checkout_subtotal_inr"] = float(listing_tax["subtotalInr"])
                item.metadata_json["_checkout_gst_inr"] = float(listing_tax["gstInr"])
                item.metadata_json["_checkout_total_inr"] = float(listing_tax["totalInr"])
            if item.product_type == CartProductType.DOMAIN_REGISTRATION:
                item.metadata_json["_checkout_registrant"] = registrant or {}
                # Persist THIS item's selected period — never a cart-global value.
                item_period = max(
                    1,
                    int((item.metadata_json or {}).get("period") or 1),
                )
                item.metadata_json["_checkout_period_years"] = item_period
                item.metadata_json["_checkout_batch_id"] = batch_id
                # Create CREATED order BEFORE payment so Razorpay webhook can provision
                # even if the browser never reaches /cart/checkout/verify.
                pending = await self._create_pending_domain_registration_order(
                    item=item,
                    buyer=buyer,
                    razorpay_order_id=rzp_order["id"],
                    batch_id=batch_id,
                )
                item.metadata_json["_checkout_registration_order_id"] = str(pending.id)
            await self._repo.save(item)

        await self._session.commit()

        return {
            "orderId": rzp_order["id"],
            "amount": charge_amount,
            "amountInr": order_amount_inr,
            "currency": charge_currency,
            "keyId": rzp.get_key_id(),
            "itemCount": len(valid_items),
            "currencyFallback": currency_fallback,
            # Display-only for Razorpay Checkout UI (not persisted as new DB columns).
            "buyerName": resolved_buyer_name,
            "buyerEmail": resolved_buyer_email,
            "buyerPhone": resolved_buyer_phone,
            "paymentDescription": payment_description,
            "paymentCategories": categories_summary,
        }

    async def verify_checkout_payment(
        self,
        buyer: AppUser,
        req: CartVerifyRequest,
    ) -> dict[str, Any]:
        logger.info(
            "[CHECKOUT_VERIFY_PAYMENT] Starting Razorpay payment verification: razorpay_order_id=%s, razorpay_payment_id=%s, buyer_id=%s",
            req.razorpay_order_id,
            req.razorpay_payment_id,
            buyer.id,
        )
        if not rzp.verify_payment_signature(
            req.razorpay_order_id,
            req.razorpay_payment_id,
            req.razorpay_signature,
        ):
            logger.error(
                "[CHECKOUT_VERIFY_PAYMENT] Razorpay payment signature verification failed: razorpay_order_id=%s, razorpay_payment_id=%s",
                req.razorpay_order_id,
                req.razorpay_payment_id,
            )
            from app.service.user.edge_points_service import EdgePointsService

            await EdgePointsService.cancel_redemption(self._session, req.razorpay_order_id)
            await self._session.commit()
            raise AppException("Payment verification failed.", status_code=400)

        try:
            rzp.assert_captured_payment_for_order(
                payment_id=req.razorpay_payment_id,
                order_id=req.razorpay_order_id,
                expected_buyer_id=str(buyer.id),
            )
            logger.info(
                "[CHECKOUT_VERIFY_PAYMENT] Razorpay captured payment verified successfully: razorpay_order_id=%s, razorpay_payment_id=%s",
                req.razorpay_order_id,
                req.razorpay_payment_id,
            )
        except ValueError as exc:
            logger.error(
                "[CHECKOUT_VERIFY_PAYMENT] Razorpay captured payment assertion ValueError: razorpay_order_id=%s, error=%s",
                req.razorpay_order_id,
                exc,
            )
            from app.service.user.edge_points_service import EdgePointsService

            await EdgePointsService.cancel_redemption(self._session, req.razorpay_order_id)
            await self._session.commit()
            raise AppException(str(exc) or "Payment verification failed.", status_code=400) from exc
        except Exception as exc:
            logger.exception(
                "[CHECKOUT_VERIFY_PAYMENT] Razorpay lookup error: razorpay_order_id=%s, error=%s",
                req.razorpay_order_id,
                exc,
            )
            from app.service.user.edge_points_service import EdgePointsService

            await EdgePointsService.cancel_redemption(self._session, req.razorpay_order_id)
            await self._session.commit()
            raise AppException("Payment verification failed.", status_code=400)

        # Serialize concurrent verify attempts for the same buyer cart.
        try:
            items = await self._repo.get_by_user_for_update(buyer.id)
        except PendingRollbackError:
            logger.warning(
                "cart.checkout.verify.pending_rollback_before_cart_lock order=%s",
                req.razorpay_order_id,
            )
            await _reset_aborted_session(self._session)
            items = await self._repo.get_by_user_for_update(buyer.id)
        checkout_items = [
            it for it in items
            if (it.metadata_json or {}).get("_checkout_razorpay_order_id") == req.razorpay_order_id
        ]

        from app.service.platform.track_record_service import TrackRecordService

        track_service = TrackRecordService(self._session)

        if not checkout_items:
            # Signature + payment already verified — cart may have been cleared on a prior verify.
            # Still attempt provision for any CREATED/PAYMENT_COMPLETED orders tied to this Razorpay order
            # (created at checkout so webhook/verify can fulfill without cart lines).
            try:
                recovered = await self._provision_pending_orders_for_payment(
                    buyer=buyer,
                    razorpay_order_id=req.razorpay_order_id,
                    razorpay_payment_id=req.razorpay_payment_id,
                )
            except PendingRollbackError:
                logger.warning(
                    "cart.checkout.verify.pending_rollback_empty_cart order=%s",
                    req.razorpay_order_id,
                )
                await _reset_aborted_session(self._session)
                recovered = await self._provision_pending_orders_for_payment(
                    buyer=buyer,
                    razorpay_order_id=req.razorpay_order_id,
                    razorpay_payment_id=req.razorpay_payment_id,
                )
            backfilled = await track_service.backfill_from_registration_orders(
                razorpay_order_id=req.razorpay_order_id,
                razorpay_payment_id=req.razorpay_payment_id,
                cart_batch_id=req.razorpay_order_id,
            )
            if recovered:
                ok_domains = [
                    str(r.get("domain")).lower().strip()
                    for r in recovered
                    if r.get("success") is True and r.get("domain")
                ]
                # Payment verified — clear matching cart lines even if checkout
                # metadata was stripped by a Razorpay dismiss/cancel race.
                try:
                    await self.remove_fulfilled_cart_items_for_payment(
                        buyer.id,
                        razorpay_order_id=req.razorpay_order_id,
                        domains=ok_domains,
                    )
                except Exception:
                    logger.exception(
                        "cart.checkout.verify.recovered_cart_cleanup_failed order=%s",
                        req.razorpay_order_id,
                    )
            try:
                await self._session.commit()
            except PendingRollbackError:
                logger.warning(
                    "cart.checkout.verify.pending_rollback_empty_cart_commit order=%s",
                    req.razorpay_order_id,
                )
                await _reset_aborted_session(self._session)
            if recovered:
                ok_count = sum(1 for r in recovered if r.get("success") is not False)
                fail_count = len(recovered) - ok_count
                logger.info(
                    "cart.checkout.verify.recovered_pending_orders order=%s payment=%s ok=%s fail=%s",
                    req.razorpay_order_id,
                    req.razorpay_payment_id,
                    ok_count,
                    fail_count,
                )
                return {
                    "success": fail_count == 0 and ok_count > 0,
                    "message": (
                        "Payment verified; domain registration recovered from pending orders."
                        if fail_count == 0
                        else "Payment verified but one or more domain registrations failed. Contact support."
                    ),
                    "results": recovered,
                    "purchasedCount": ok_count,
                    "totalItems": len(recovered),
                    "alreadyProcessed": False,
                    "recoveredFromPendingOrders": True,
                    "trackRecordsBackfilled": backfilled,
                    "needsAttention": fail_count > 0,
                }
            if backfilled:
                logger.info(
                    "cart.checkout.verify.backfilled_track_records order=%s payment=%s count=%s",
                    req.razorpay_order_id,
                    req.razorpay_payment_id,
                    backfilled,
                )
            logger.error(
                "cart.checkout.verify.no_cart_items_no_orders order=%s payment=%s buyer=%s",
                req.razorpay_order_id,
                req.razorpay_payment_id,
                buyer.id,
            )
            return {
                "success": False,
                "message": (
                    "Payment was received but no cart items or registration orders were found "
                    "to fulfill. Contact support with your payment ID — do not pay again."
                ),
                "results": [],
                "purchasedCount": 0,
                "totalItems": 0,
                "alreadyProcessed": True,
                "trackRecordsBackfilled": backfilled,
                "needsAttention": True,
            }

        from app.service.user.edge_points_service import EdgePointsService
        from app.service.platform.track_record_service import (
            TrackRecordCategory,
            PaymentStatus,
            FulfillmentStatus,
            OverallStatus,
        )

        await EdgePointsService.confirm_redemption(self._session, req.razorpay_order_id)

        results: list[dict] = []

        for item in checkout_items:
            meta = dict(item.metadata_json or {})
            prior_payment = meta.get("_fulfilled_razorpay_payment_id")
            if prior_payment and prior_payment == req.razorpay_payment_id:
                results.append({
                    "itemId": str(item.id),
                    "success": True,
                    "alreadyProcessed": True,
                })
                continue

            # Determine category & product info for Track Record
            product_type = item.product_type
            # Only meaningful for TECHNOLOGY lines; default keeps non-tech lines
            # (domain/marketplace/venture) on their own fulfillment rules.
            is_tech_service = False
            is_reseller = (
                str(meta.get("registrar") or meta.get("priceSource") or "").lower() == "reseller"
                or str(meta.get("price_source") or "").lower() == "reseller"
                or bool(meta.get("resellerclub_order_id"))
            )
            if product_type == CartProductType.DOMAIN_REGISTRATION:
                tr_category = (
                    TrackRecordCategory.DOMAIN_REGISTRATION_RESELLER
                    if is_reseller
                    else TrackRecordCategory.DOMAIN_REGISTRATION_OPENPROVIDER
                )
                tr_provider = "Reseller" if is_reseller else "OpenProvider"
            elif product_type == CartProductType.DOMAIN_LISTING:
                tr_category = TrackRecordCategory.DOMAIN_MARKETPLACE
                tr_provider = "Razorpay"
            elif product_type == CartProductType.TECHNOLOGY:
                # Provider-powered technology services (VPN, AI Business Suite,
                # Appointment Booking, Invoice AI, Link in Bio, …) are
                # subscriptions — a distinct category from one-time software
                # products. The frontend stamps `serviceSlug` in the cart item
                # metadata; the provision result is authoritative afterwards.
                is_tech_service = bool(str(meta.get("serviceSlug") or "").strip())
                tr_category = (
                    TrackRecordCategory.TECHNOLOGY_SERVICES
                    if is_tech_service
                    else TrackRecordCategory.TECHNOLOGY_PURCHASE
                )
                tr_provider = "Razorpay"
            elif product_type == CartProductType.VENTURE_DEAL:
                tr_category = TrackRecordCategory.VENTURE_DEAL_PAYMENT
                tr_provider = "Razorpay"
            else:
                tr_category = TrackRecordCategory.OTHER
                tr_provider = "Razorpay"

            item_name = _cart_item_product_name(item)
            buyer_details = _checkout_buyer_details(item, buyer)
            internal_order_id = _track_internal_order_id(
                razorpay_order_id=req.razorpay_order_id,
                item=item,
            )

            try:
                logger.info(
                    "cart.checkout.post_payment.start item=%s type=%s payment=%s",
                    item.id,
                    product_type,
                    req.razorpay_payment_id,
                )
                result = await self._process_item_post_payment(item, buyer, req.razorpay_payment_id)
                internal_order_id = _track_internal_order_id(
                    razorpay_order_id=req.razorpay_order_id,
                    item=item,
                    result=result,
                )
                meta["_fulfilled_razorpay_payment_id"] = req.razorpay_payment_id
                item.metadata_json = meta
                await self._repo.save(item)
                item_success = result.get("success") is not False
                results.append({
                    "itemId": str(item.id),
                    "success": item_success,
                    **result,
                })

                # Check if result dynamically updated registrar info
                if result.get("registrar") == "Reseller" or result.get("resellerclubOrderId"):
                    tr_category = TrackRecordCategory.DOMAIN_REGISTRATION_RESELLER
                    tr_provider = "Reseller"

                if product_type == CartProductType.TECHNOLOGY:
                    # The provision result is authoritative: a provider service
                    # (isService / subscriptionId) must be filed under Technology
                    # Services even if the cart metadata lost serviceSlug.
                    is_tech_service = bool(
                        result.get("isService") or result.get("subscriptionId")
                    ) or bool(str(meta.get("serviceSlug") or "").strip())
                    if is_tech_service and tr_category != TrackRecordCategory.TECHNOLOGY_SERVICES:
                        tr_category = TrackRecordCategory.TECHNOLOGY_SERVICES

                fulfillment_status, overall_status, error_code, error_message = (
                    _fulfillment_from_provision_result(result)
                    if product_type == CartProductType.DOMAIN_REGISTRATION
                    else _tech_fulfillment_from_result(result, is_tech_service)
                )

                if (
                    product_type == CartProductType.DOMAIN_REGISTRATION
                    and result.get("registrationOrderId")
                ):
                    from app.repository.domain_registration_order_repository import (
                        DomainRegistrationOrderRepository,
                    )

                    reg_order = await DomainRegistrationOrderRepository(self._session).get_by_id(
                        uuid.UUID(str(result["registrationOrderId"]))
                    )
                    if reg_order:
                        await track_service.record_from_registration_order(
                            reg_order,
                            cart_batch_id=req.razorpay_order_id,
                            internal_order_id=internal_order_id,
                        )
                    else:
                        await track_service.record_paid_attempt(
                            internal_order_id=internal_order_id,
                            cart_batch_id=req.razorpay_order_id,
                            category=tr_category,
                            provider_subcategory=tr_provider,
                            item_name=item_name,
                            item_id=str(item.product_id),
                            quantity_years=int(meta.get("years") or meta.get("period") or 1),
                            buyer_name=buyer_details["name"],
                            buyer_email=buyer_details["email"],
                            buyer_phone=buyer_details["phone"],
                            buyer_user_id=buyer.id,
                            amount_charged=float(meta.get("_checkout_unit_price_inr", 0.0)),
                            currency="INR",
                            payment_status=PaymentStatus.CAPTURED,
                            razorpay_order_id=req.razorpay_order_id,
                            razorpay_payment_id=req.razorpay_payment_id,
                            fulfillment_status=fulfillment_status,
                            overall_status=overall_status,
                            openprovider_domain_id=str(
                                result.get("openproviderDomainId")
                                or meta.get("openprovider_domain_id")
                                or ""
                            ),
                            error_code=error_code,
                            error_message=error_message,
                            error_source="OPENPROVIDER_OR_BACKEND" if error_code else None,
                        )
                else:
                    await track_service.record_paid_attempt(
                        internal_order_id=internal_order_id,
                        cart_batch_id=req.razorpay_order_id,
                        category=tr_category,
                        provider_subcategory=tr_provider,
                        item_name=item_name,
                        item_id=str(item.product_id),
                        quantity_years=int(meta.get("years") or meta.get("period") or 1),
                        buyer_name=buyer_details["name"],
                        buyer_email=buyer_details["email"],
                        buyer_phone=buyer_details["phone"],
                        buyer_user_id=buyer.id,
                    amount_charged=float(meta.get("_checkout_unit_price_inr", 0.0)),
                        currency="INR",
                        payment_status=PaymentStatus.CAPTURED,
                        razorpay_order_id=req.razorpay_order_id,
                        razorpay_payment_id=req.razorpay_payment_id,
                        fulfillment_status=fulfillment_status,
                        overall_status=overall_status,
                        openprovider_domain_id=str(
                            result.get("openproviderDomainId")
                            or meta.get("openprovider_domain_id")
                            or ""
                        ),
                        error_code=error_code,
                        error_message=error_message,
                        error_source="OPENPROVIDER_OR_BACKEND" if error_code else None,
                    )
                logger.info(
                    "cart.checkout.track_record.recorded internal_order_id=%s payment=%s",
                    internal_order_id,
                    req.razorpay_payment_id,
                )
            except Exception as exc:
                logger.exception(
                    "[CHECKOUT_VERIFY_PAYMENT] Post-payment processing failed for item=%s: error=%s",
                    item.id,
                    exc,
                )
                results.append({"itemId": str(item.id), "success": False, "error": str(exc)})

                # Record Track Record on Failure
                await track_service.record_paid_attempt(
                    internal_order_id=internal_order_id,
                    cart_batch_id=req.razorpay_order_id,
                    category=tr_category,
                    provider_subcategory="Razorpay / OpenProvider" if product_type == CartProductType.DOMAIN_REGISTRATION else "Razorpay",
                    item_name=item_name,
                    item_id=str(item.product_id),
                    quantity_years=int(meta.get("years") or meta.get("period") or 1),
                    buyer_name=buyer_details["name"],
                    buyer_email=buyer_details["email"],
                    buyer_phone=buyer_details["phone"],
                    buyer_user_id=buyer.id,
                    amount_charged=float(meta.get("_checkout_unit_price_inr", 0.0)),
                    currency="INR",
                    payment_status=PaymentStatus.CAPTURED,
                    razorpay_order_id=req.razorpay_order_id,
                    razorpay_payment_id=req.razorpay_payment_id,
                    fulfillment_status=FulfillmentStatus.FAILED,
                    overall_status=OverallStatus.FAILED,
                    error_code="PROVISIONING_ERROR",
                    error_message=str(exc),
                    error_source="OPENPROVIDER_OR_BACKEND",
                )

        fulfilled_domains: list[str] = []
        for r in results:
            if isinstance(r, dict) and r.get("domain"):
                fulfilled_domains.append(str(r["domain"]).lower().strip())
        for it in checkout_items:
            meta = it.metadata_json or {}
            if meta.get("domainName"):
                fulfilled_domains.append(str(meta["domainName"]).lower().strip())

        deleted_count = await self.remove_fulfilled_cart_items_for_payment(
            buyer.id,
            razorpay_order_id=req.razorpay_order_id,
            domains=fulfilled_domains,
        )

        purchased_ids = [
            uuid.UUID(r["itemId"])
            for r in results
            if r.get("success") is not False and r.get("itemId")
        ]

        try:
            await self._session.commit()
        except PendingRollbackError:
            logger.warning(
                "cart.checkout.verify.pending_rollback_on_commit order=%s",
                req.razorpay_order_id,
            )
            await _reset_aborted_session(self._session)
        logger.info(
            "[CHECKOUT_VERIFY_PAYMENT] DB transaction committed successfully for razorpay_order_id=%s, buyer_id=%s, deleted_cart_items=%s",
            req.razorpay_order_id, buyer.id, deleted_count,
        )

        fail_count = sum(1 for r in results if r.get("success") is False)
        purchased_count = max(len(purchased_ids), deleted_count, len(checkout_items) - fail_count)
        return {
            "success": fail_count == 0 and purchased_count > 0,
            "message": (
                "Cart checkout completed."
                if fail_count == 0
                else "Payment received but some items failed provisioning. Contact support."
            ),
            "results": results,
            "purchasedCount": purchased_count,
            "totalItems": len(checkout_items),
            "needsAttention": fail_count > 0,
        }

    async def cancel_checkout_order(
        self,
        buyer: AppUser,
        razorpay_order_id: str,
    ) -> dict[str, Any]:
        from app.service.user.edge_points_service import EdgePointsService

        await EdgePointsService.cancel_redemption(self._session, razorpay_order_id)

        items = await self._repo.get_by_user(buyer.id)
        cleared = 0
        checkout_keys = (
            "_checkout_razorpay_order_id",
            "_checkout_buyer_name",
            "_checkout_buyer_email",
            "_checkout_buyer_phone",
            "_checkout_registration_order_id",
            "_checkout_batch_id",
            "_checkout_period_years",
            "_checkout_registrant",
            "_checkout_payment_currency",
        )
        for item in items:
            meta = dict(item.metadata_json or {})
            if meta.get("_checkout_razorpay_order_id") != razorpay_order_id:
                continue
            for key in checkout_keys:
                meta.pop(key, None)
            item.metadata_json = meta or None
            await self._repo.save(item)
            cleared += 1

        # Soft-expire pending CREATED orders for this Razorpay order (never DELETE rows).
        from app.repository.domain_registration_order_repository import (
            DomainRegistrationOrderRepository,
        )
        from app.utils.registration_enums import RegistrationOrderStatus

        orders_repo = DomainRegistrationOrderRepository(self._session)
        for order in await orders_repo.list_by_razorpay_order_id(razorpay_order_id):
            if order.status == RegistrationOrderStatus.CREATED:
                order.status = RegistrationOrderStatus.EXPIRED
                order.provision_message = (
                    "Checkout cancelled before payment; pending registration order expired."
                )
                await orders_repo.save(order)

        await self._session.commit()
        return {"success": True, "clearedItems": cleared}

    async def _resolve_line_total(self, item: CartItem, buyer: AppUser) -> float | None:
        addon_keys = [k.strip() for k in (item.addon_services or "").split(",") if k.strip()]
        addon_amount = sum(float(ADDON_PRICES.get(k, 0)) for k in addon_keys)
        co_brother_fee = COBROTHER_FEE_INR if item.co_brother_opt_in else 0.0

        base_price = 0.0

        if item.product_type == CartProductType.DOMAIN_LISTING:
            from app.entity.cobranding.domain_listing_entity import DomainListing
            from sqlalchemy import select

            stmt = select(DomainListing).where(
                DomainListing.id == item.product_id,
                DomainListing.is_deleted.is_(False),
            )
            result = await self._session.execute(stmt)
            listing = result.scalar_one_or_none()
            if listing is None or listing.domain_status not in (
                DomainListingStatus.AVAILABLE,
                DomainListingStatus.PENDING,
            ):
                return None
            if listing.listed_by_user_id == buyer.id:
                return None
            base_price = float(listing.asking_price or 0)

        elif item.product_type == CartProductType.TECHNOLOGY:
            from app.entity.cocreation.software_entity import Software
            from app.entity.technology_services.technology_service_entity import (
                TechnologyServiceEntity,
            )
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            stmt = (
                select(Software)
                .where(Software.id == item.product_id, Software.is_deleted.is_(False))
                .options(selectinload(Software.pricing_plans))
            )
            result = await self._session.execute(stmt)
            software = result.scalar_one_or_none()
            if software is not None:
                if software.software_status != SoftwareStatus.AVAILABLE:
                    return None
                if software.listed_by_user_id == buyer.id:
                    return None
                if software.purchase_type == SoftwarePurchaseType.AUCTION:
                    return None

                base_price = float(software.price or 0)
                if item.selected_plan and software.pricing_plans:
                    key_mapping = {
                        "1_MONTH": "ONE_MONTH",
                        "3_MONTHS": "THREE_MONTHS",
                        "6_MONTHS": "SIX_MONTHS",
                        "12_MONTHS": "TWELVE_MONTHS",
                    }
                    mapped = key_mapping.get(item.selected_plan, item.selected_plan)
                    try:
                        plan_enum = TechnologyPricingPlanDuration(mapped)
                        plan = next(
                            (p for p in software.pricing_plans if p.plan_duration == plan_enum and p.is_active),
                            None,
                        )
                        if plan:
                            base_price = float(plan.price)
                    except ValueError:
                        pass
            else:
                # Fallback: technology-service catalogue entry (provider-powered
                # services like AI Business Suite live in technology_services_catalogue,
                # not software_listings).
                tech_service = await self._cart_service._get_technology_service(item.product_id)
                if tech_service is None:
                    tech_service = await self._cart_service._get_technology_service_fallback(item.product_id)
                if tech_service is None or not (
                    getattr(tech_service, "is_available", True) if not isinstance(tech_service, dict) else tech_service.get("is_available", True)
                ):
                    return None

                plans_json = getattr(tech_service, "plans_json", None) if not isinstance(tech_service, dict) else tech_service.get("plans_json")
                override_monthly = getattr(tech_service, "price_override_monthly", None) if not isinstance(tech_service, dict) else tech_service.get("price_override_monthly")
                override_annually = getattr(tech_service, "price_override_annually", None) if not isinstance(tech_service, dict) else tech_service.get("price_override_annually")
                base_price = CartService._tech_service_plan_price_inr(
                    plans_json,
                    item.selected_plan,
                    item.metadata_json or {},
                    override_monthly=override_monthly,
                    override_annually=override_annually,
                )

        elif item.product_type == CartProductType.VENTURE_DEAL:
            from app.entity.coventure.venture_entity import Venture
            from sqlalchemy import select

            stmt = select(Venture).where(
                Venture.id == item.product_id,
                Venture.is_deleted.is_(False),
            )
            result = await self._session.execute(stmt)
            venture = result.scalar_one_or_none()
            if venture is None or not CartService._is_venture_available(venture):
                return None
            if venture.listed_by_user_id == buyer.id:
                return None
            brand = venture.brand_details if hasattr(venture, "brand_details") else None
            if brand and hasattr(brand, "deal_value"):
                base_price = float(brand.deal_value or 0)

        elif item.product_type == CartProductType.DOMAIN_REGISTRATION:
            meta = item.metadata_json or {}
            base_price = float(meta.get("price", 0))

        return round(base_price + addon_amount + co_brother_fee, 2)

    async def _process_item_post_payment(
        self,
        item: CartItem,
        buyer: AppUser,
        razorpay_payment_id: str,
    ) -> dict[str, Any]:
        meta = item.metadata_json or {}
        buyer_name = meta.get("_checkout_buyer_name", "")
        buyer_email = meta.get("_checkout_buyer_email", buyer.email or "")
        buyer_phone = meta.get("_checkout_buyer_phone", buyer.phone_number or "")

        if item.product_type == CartProductType.DOMAIN_LISTING:
            return await self._complete_domain_purchase(item, buyer, razorpay_payment_id, buyer_name, buyer_email, buyer_phone)
        elif item.product_type == CartProductType.TECHNOLOGY:
            return await self._complete_technology_purchase(item, buyer, razorpay_payment_id, buyer_name, buyer_email, buyer_phone)
        elif item.product_type == CartProductType.VENTURE_DEAL:
            return await self._complete_venture_purchase(item, buyer, razorpay_payment_id)
        elif item.product_type == CartProductType.DOMAIN_REGISTRATION:
            return await self._complete_domain_registration(
                item, buyer, razorpay_payment_id
            )
        return {}

    @staticmethod
    def _require_registrant(registrant: dict[str, Any] | None) -> None:
        if not isinstance(registrant, dict):
            raise AppException(
                "Registrant details are required to register domains.",
                status_code=400,
            )
        for key in ("firstName", "lastName", "email", "phone", "street", "city", "state", "zip"):
            if not str(registrant.get(key) or "").strip():
                raise AppException(
                    f"Registrant field '{key}' is required to register domains.",
                    status_code=400,
                )
        gstin_raw = str(registrant.get("gstin") or "").strip()
        if gstin_raw:
            from app.utils.field_validators import normalize_gstin

            try:
                registrant["gstin"] = normalize_gstin(gstin_raw)
            except ValueError as exc:
                raise AppException(str(exc), status_code=400) from exc
        else:
            registrant.pop("gstin", None)

    async def _revalidate_domain_registration_items(
        self,
        items: list[CartItem],
    ) -> None:
        """Re-check availability + each item's live period price before Razorpay.

        Never trust cart-cached ``isPremium`` or prices. Fresh OpenProvider
        CheckDomain + GetPrice(period=N) are authoritative. Premium GetPrice
        failures abort checkout (no stale charge).
        """
        from app.integrations.openprovider.client import tld_min_registration_years
        from app.service.domain.domain_registration_service import DomainRegistrationService

        svc = DomainRegistrationService(self._session)
        failures: list[dict[str, str]] = []

        for item in items:
            meta = item.metadata_json or {}
            domain = str(meta.get("domainName") or "").lower().strip()
            if not domain or "." not in domain:
                failures.append({"domain": domain or str(item.product_id), "reason": "unavailable"})
                continue

            tld = str(meta.get("tld") or domain.split(".", 1)[1]).lstrip(".")
            min_years = max(
                1,
                int(meta.get("minPeriodYears") or tld_min_registration_years(tld)),
            )
            period_years = max(1, int(meta.get("period") or min_years), min_years)

            try:
                check = await svc.check_registration_domain(domain)
            except AppException as exc:
                failures.append({
                    "domain": domain,
                    "reason": "unavailable",
                    "message": str(exc.message),
                })
                continue
            except Exception as exc:
                failures.append({
                    "domain": domain,
                    "reason": "unavailable",
                    "message": str(exc),
                })
                continue

            if check.status != "available":
                failures.append({"domain": domain, "reason": "unavailable"})
                continue

            # Authoritative premium flag from live check — ignore cart cache.
            live_is_premium = bool(getattr(check, "isPremium", False))

            # Aftermarket (Afternic/Sedo) items must NEVER be re-quoted through
            # GetPrice: it returns the standard registry price for registry-
            # taken domains. The live aftermarket check price is authoritative
            # and the managed-acquisition flag is preserved so these can never
            # go through the normal online registration checkout.
            premium_provider = str(meta.get("premiumProvider") or "").strip().lower()
            if premium_provider in ("afternic", "sedo"):
                try:
                    unit_inr = float(getattr(check, "unitPrice") or 0)
                except (TypeError, ValueError):
                    unit_inr = 0.0
                if unit_inr <= 0:
                    failures.append({
                        "domain": domain,
                        "reason": "premium_price_unavailable",
                        "message": (
                            "Unable to verify the latest aftermarket premium price. "
                            "Please try again."
                        ),
                    })
                    continue
                meta = dict(meta)
                meta["price"] = unit_inr
                meta["pricePerYear"] = unit_inr
                meta["domainName"] = domain
                meta["tld"] = tld
                meta["period"] = 1
                meta["minPeriodYears"] = min_years
                meta["priceSource"] = (
                    getattr(check, "priceSource") or "aftermarket_check"
                )
                meta["commissionRate"] = None
                meta["isPremium"] = True
                meta["registryTier"] = "premium"
                meta["premiumProvider"] = premium_provider
                meta["isManagedAcquisition"] = True
                item.metadata_json = meta
                await self._repo.save(item)
                continue

            try:
                quote = await svc.quote_registration_period_price(
                    domain,
                    period_years,
                    require_live_price=True,
                )
            except AppException as exc:
                reason = (
                    "premium_price_unavailable"
                    if live_is_premium
                    or "premium domain price" in str(exc.message or "").lower()
                    else "price_changed"
                )
                failures.append({
                    "domain": domain,
                    "reason": reason,
                    "message": str(exc.message),
                })
                continue
            except Exception as exc:
                reason = "premium_price_unavailable" if live_is_premium else "price_changed"
                msg = (
                    "Unable to verify the latest premium domain price. Please try again."
                    if live_is_premium
                    else str(exc)
                )
                failures.append({
                    "domain": domain,
                    "reason": reason,
                    "message": msg,
                })
                continue

            is_premium = bool(quote.get("isPremium", live_is_premium))
            period_total = float(quote.get("price") or 0)
            per_year = float(quote.get("pricePerYear") or 0)
            if period_total <= 0:
                if is_premium:
                    failures.append({
                        "domain": domain,
                        "reason": "premium_price_unavailable",
                        "message": (
                            "Unable to verify the latest premium domain price. "
                            "Please try again."
                        ),
                    })
                else:
                    failures.append({"domain": domain, "reason": "unavailable"})
                continue

            meta = dict(meta)
            meta["price"] = period_total
            meta["pricePerYear"] = per_year
            meta["domainName"] = domain
            meta["tld"] = tld
            meta["period"] = int(quote.get("periodYears") or period_years)
            meta["minPeriodYears"] = int(
                quote.get("minPeriodYears") or min_years
            )
            meta["priceSource"] = quote.get("priceSource")
            meta["commissionRate"] = quote.get("commissionRate")
            meta["isPremium"] = is_premium
            meta["registryTier"] = quote.get("registryTier") or (
                "premium" if is_premium else "standard"
            )
            meta["providerUnitPriceInr"] = quote.get("providerUnitPriceInr")
            meta["providerCurrency"] = quote.get("providerCurrency")
            item.metadata_json = meta
            await self._repo.save(item)

            if is_premium:
                logger.info(
                    "analytics.premium_checkout domain=%s period=%s price=%s",
                    domain,
                    meta["period"],
                    period_total,
                )

        if failures:
            premium_fail = any(
                f.get("reason") == "premium_price_unavailable" for f in failures
            )
            if premium_fail and len(failures) == 1:
                msg = (
                    failures[0].get("message")
                    or "Unable to verify the latest premium domain price. Please try again."
                )
            else:
                names = ", ".join(f["domain"] for f in failures)
                msg = (
                    f"Some domains are no longer available or their price could not "
                    f"be verified: {names}. Remove them from your cart and try again."
                )
            exc = AppException(msg, status_code=409 if not premium_fail else 502)
            exc.failed_domains = failures  # type: ignore[attr-defined]
            raise exc

    async def _create_pending_domain_registration_order(
        self,
        *,
        item: CartItem,
        buyer: AppUser,
        razorpay_order_id: str,
        batch_id: str | None,
    ):
        """INSERT-only: create a CREATED order so webhook can provision after payment."""
        from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
        from app.repository.domain_registration_order_repository import (
            DomainRegistrationOrderRepository,
        )
        from app.utils.domain_gst import domain_price_breakdown
        from app.utils.registration_enums import RegistrationOrderStatus

        meta = item.metadata_json or {}
        domain = str(meta.get("domainName") or "").lower().strip()
        if not domain or "." not in domain:
            raise AppException("Domain registration cart item is missing domainName.")

        registrant = meta.get("_checkout_registrant") or {}
        period = max(
            1,
            int(
                meta.get("_checkout_period_years")
                or meta.get("period")
                or meta.get("minPeriodYears")
                or 1
            ),
        )
        period_total = float(meta.get("price") or 0)
        per_year = float(meta.get("pricePerYear") or 0)
        if period_total <= 0:
            raise AppException(f"Missing registration price for {domain}.")
        if per_year <= 0:
            per_year = round(period_total / period, 2)

        pricing = domain_price_breakdown(period_total, years=1)
        name, ext = domain.split(".", 1)
        batch_uuid = uuid.UUID(str(batch_id)) if batch_id else None

        order = DomainRegistrationOrder(
            domain_name=name,
            domain_extension="." + ext,
            buyer_id=buyer.id,
            buyer_full_name=f"{registrant.get('firstName', '')} {registrant.get('lastName', '')}".strip(),
            buyer_email=str(registrant.get("email") or buyer.email or ""),
            buyer_phone=str(registrant.get("phone") or ""),
            street=str(registrant.get("street") or ""),
            city=str(registrant.get("city") or ""),
            state=str(registrant.get("state") or ""),
            zip_code=str(registrant.get("zip") or ""),
            country=str(registrant.get("country") or "IN"),
            buyer_gstin=(
                str(registrant.get("gstin") or "").strip().upper() or None
            ),
            period_years=period,
            subtotal_inr=pricing["subtotalInr"],
            gst_inr=pricing["gstInr"],
            price_inr=pricing["totalInr"],
            quoted_unit_price_inr=per_year,
            price_source="cart_checkout",
            is_premium=bool(meta.get("isPremium")),
            registry_tier=str(
                meta.get("registryTier")
                or ("premium" if meta.get("isPremium") else "standard")
            ),
            provider_unit_price_inr=(
                float(meta["providerUnitPriceInr"])
                if meta.get("providerUnitPriceInr") is not None
                else None
            ),
            status=RegistrationOrderStatus.CREATED,
            razorpay_order_id=razorpay_order_id,
            batch_id=batch_uuid,
            provision_message="Awaiting Razorpay payment capture before OpenProvider registration.",
        )
        orders_repo = DomainRegistrationOrderRepository(self._session)
        order = await orders_repo.create(order)
        logger.info(
            "cart.checkout.pending_domain_order_created domain=%s order_id=%s rzp_order=%s",
            domain,
            order.id,
            razorpay_order_id,
        )
        return order

    async def _provision_pending_orders_for_payment(
        self,
        *,
        buyer: AppUser,
        razorpay_order_id: str,
        razorpay_payment_id: str,
    ) -> list[dict[str, Any]]:
        from app.repository.domain_registration_order_repository import (
            DomainRegistrationOrderRepository,
        )
        from app.service.domain.domain_registration_service import DomainRegistrationService
        from app.utils.registration_enums import RegistrationOrderStatus

        orders_repo = DomainRegistrationOrderRepository(self._session)
        try:
            listed = await orders_repo.list_by_razorpay_order_id(razorpay_order_id)
        except PendingRollbackError:
            logger.warning(
                "cart.checkout.recover_pending.pending_rollback order=%s",
                razorpay_order_id,
            )
            await _reset_aborted_session(self._session)
            listed = await orders_repo.list_by_razorpay_order_id(razorpay_order_id)
        orders = [
            o
            for o in listed
            if o.buyer_id == buyer.id
        ]
        if not orders:
            return []

        svc = DomainRegistrationService(self._session)
        results: list[dict[str, Any]] = []
        for order in orders:
            domain = f"{order.domain_name}{order.domain_extension}"
            if order.status == RegistrationOrderStatus.ACTIVE or (
                order.status == RegistrationOrderStatus.REGISTRATION_PENDING
                and str(order.open_provider_domain_id or "").strip()
            ):
                results.append({
                    "type": "DOMAIN_REGISTRATION",
                    "domain": domain,
                    "registrationOrderId": str(order.id),
                    "status": order.status.value,
                    "success": True,
                    "alreadyProcessed": True,
                })
                continue

            order.razorpay_payment_id = razorpay_payment_id
            if order.status in (
                RegistrationOrderStatus.CREATED,
                RegistrationOrderStatus.EXPIRED,
                RegistrationOrderStatus.PAYMENT_FAILED,
                RegistrationOrderStatus.FAILED,
                RegistrationOrderStatus.PROVISION_FAILED,
            ):
                order.status = RegistrationOrderStatus.PAYMENT_COMPLETED
            await orders_repo.save(order)

            try:
                await svc.provision_order(order)
                await orders_repo.save(order)
            except Exception as exc:
                logger.exception(
                    "cart.checkout.recover_pending.provision_failed domain=%s err=%s",
                    domain,
                    exc,
                )
                await _reset_aborted_session(self._session)
                try:
                    fresh = await orders_repo.get_by_id(order.id)
                except PendingRollbackError:
                    await _reset_aborted_session(self._session)
                    fresh = await orders_repo.get_by_id(order.id)
                if fresh is not None:
                    order = fresh
                if order.status in (
                    RegistrationOrderStatus.ACTIVE,
                    RegistrationOrderStatus.REGISTRATION_PENDING,
                ):
                    st = order.status.value
                    results.append({
                        "type": "DOMAIN_REGISTRATION",
                        "domain": domain,
                        "registrationOrderId": str(order.id),
                        "status": st,
                        "success": True,
                        "alreadyProcessed": True,
                    })
                    continue
                order.status = RegistrationOrderStatus.PROVISION_FAILED
                order.provision_message = str(exc)[:500]
                await orders_repo.save(order)
                results.append({
                    "type": "DOMAIN_REGISTRATION",
                    "domain": domain,
                    "registrationOrderId": str(order.id),
                    "status": order.status.value,
                    "success": False,
                    "error": str(exc),
                })
                continue

            st = order.status.value if hasattr(order.status, "value") else str(order.status)
            ok = st.upper() in ("ACTIVE", "REGISTRATION_PENDING")
            results.append({
                "type": "DOMAIN_REGISTRATION",
                "domain": domain,
                "registrationOrderId": str(order.id),
                "status": st,
                "success": ok,
                "error": None if ok else (order.provision_message or st),
                "message": order.provision_message,
                "openproviderDomainId": order.open_provider_domain_id,
            })
        return results

    async def _complete_domain_registration(
        self,
        item: CartItem,
        buyer: AppUser,
        razorpay_payment_id: str,
    ) -> dict[str, Any]:
        from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
        from app.repository.domain_registration_order_repository import (
            DomainRegistrationOrderRepository,
        )
        from app.service.domain.domain_registration_service import DomainRegistrationService
        from app.utils.domain_gst import domain_price_breakdown
        from app.utils.registration_enums import RegistrationOrderStatus

        meta = item.metadata_json or {}
        domain = str(meta.get("domainName") or "").lower().strip()
        if not domain or "." not in domain:
            raise AppException("Domain registration cart item is missing domainName.")

        orders_repo = DomainRegistrationOrderRepository(self._session)
        order = None
        pending_id = meta.get("_checkout_registration_order_id")
        if pending_id:
            try:
                order = await orders_repo.get_by_id(uuid.UUID(str(pending_id)))
            except (ValueError, TypeError):
                order = None

        if order is None:
            # Fallback: create order on verify (legacy carts created before pending-order fix).
            registrant = meta.get("_checkout_registrant") or {}
            period = max(
                1,
                int(
                    meta.get("_checkout_period_years")
                    or meta.get("period")
                    or meta.get("minPeriodYears")
                    or 1
                ),
            )
            period_total = float(meta.get("price") or 0)
            per_year = float(meta.get("pricePerYear") or 0)
            if period_total <= 0:
                raise AppException(f"Missing registration price for {domain}.")
            if per_year <= 0:
                per_year = round(period_total / period, 2)

            pricing = domain_price_breakdown(period_total, years=1)
            name, ext = domain.split(".", 1)
            batch_raw = meta.get("_checkout_batch_id")
            batch_id = uuid.UUID(str(batch_raw)) if batch_raw else None
            rzp_order_id = meta.get("_checkout_razorpay_order_id")

            order = DomainRegistrationOrder(
                domain_name=name,
                domain_extension="." + ext,
                buyer_id=buyer.id,
                buyer_full_name=f"{registrant.get('firstName', '')} {registrant.get('lastName', '')}".strip(),
                buyer_email=str(registrant.get("email") or ""),
                buyer_phone=str(registrant.get("phone") or ""),
                street=str(registrant.get("street") or ""),
                city=str(registrant.get("city") or ""),
                state=str(registrant.get("state") or ""),
                zip_code=str(registrant.get("zip") or ""),
                country=str(registrant.get("country") or "IN"),
                buyer_gstin=(
                    str(registrant.get("gstin") or "").strip().upper() or None
                ),
                period_years=period,
                subtotal_inr=pricing["subtotalInr"],
                gst_inr=pricing["gstInr"],
                price_inr=pricing["totalInr"],
                quoted_unit_price_inr=per_year,
                price_source="cart_checkout",
                is_premium=bool(meta.get("isPremium")),
                registry_tier=str(
                    meta.get("registryTier")
                    or ("premium" if meta.get("isPremium") else "standard")
                ),
                provider_unit_price_inr=(
                    float(meta["providerUnitPriceInr"])
                    if meta.get("providerUnitPriceInr") is not None
                    else None
                ),
                status=RegistrationOrderStatus.PAYMENT_COMPLETED,
                razorpay_order_id=rzp_order_id,
                razorpay_payment_id=razorpay_payment_id,
                batch_id=batch_id,
            )
            order = await orders_repo.create(order)
        else:
            order.razorpay_payment_id = razorpay_payment_id
            if order.status in (
                RegistrationOrderStatus.CREATED,
                RegistrationOrderStatus.EXPIRED,
            ):
                order.status = RegistrationOrderStatus.PAYMENT_COMPLETED
            await orders_repo.save(order)

        # COMMIT ORDER RECORD IMMEDIATELY AFTER PAYMENT VERIFICATION SUCCESS
        try:
            await self._session.commit()
            logger.info(
                "[DOMAIN_REGISTRATION_PERSISTENCE] DomainRegistrationOrder created and COMMITTED to DB: order_id=%s, domain=%s, razorpay_payment_id=%s, status=%s",
                order.id, domain, razorpay_payment_id, order.status,
            )
        except Exception as exc:
            logger.exception(
                "[DOMAIN_REGISTRATION_PERSISTENCE] Failed to commit DomainRegistrationOrder to DB: order_id=%s, domain=%s, error=%s",
                order.id, domain, exc,
            )
            raise

        if order.is_premium:
            logger.info(
                "analytics.premium_purchased domain=%s order_id=%s price_inr=%s",
                domain,
                order.id,
                order.price_inr,
            )

        batch_id = order.batch_id
        period = order.period_years
        if order.status == RegistrationOrderStatus.ACTIVE:
            return {
                "type": "DOMAIN_REGISTRATION",
                "domain": domain,
                "registrationOrderId": str(order.id),
                "batchId": str(batch_id) if batch_id else None,
                "periodYears": period,
                "status": order.status.value,
                "success": True,
                "provisionSuccess": True,
                "alreadyProcessed": True,
                "error": None,
                "message": order.provision_message,
                "openproviderDomainId": order.open_provider_domain_id,
                "isPremium": bool(getattr(order, "is_premium", False)),
            }

        svc = DomainRegistrationService(self._session)
        logger.info(
            "[OPENPROVIDER_PROVISIONING] Initiating OpenProvider registration request for domain=%s, order_id=%s",
            domain, order.id,
        )

        try:
            await svc.provision_order(order)
            await orders_repo.save(order)
            await self._session.commit()
            logger.info(
                "[OPENPROVIDER_PROVISIONING] Provisioning completed for domain=%s, order_id=%s, final_status=%s",
                domain, order.id, order.status,
            )
        except Exception as exc:
            logger.exception(
                "[OPENPROVIDER_PROVISIONING] OpenProvider provisioning failed for domain=%s, order_id=%s: %s",
                domain, order.id, exc,
            )
            try:
                await self._session.rollback()
            except Exception:
                pass
            try:
                fresh = await orders_repo.get_by_id(order.id)
            except PendingRollbackError:
                await _reset_aborted_session(self._session)
                fresh = await orders_repo.get_by_id(order.id)
            if fresh is not None:
                order = fresh
            if order.status in (
                RegistrationOrderStatus.ACTIVE,
                RegistrationOrderStatus.REGISTRATION_PENDING,
            ):
                logger.info(
                    "[OPENPROVIDER_PROVISIONING] Browser verify error ignored; "
                    "order already %s domain=%s order_id=%s",
                    order.status, domain, order.id,
                )
            else:
                order.status = RegistrationOrderStatus.PROVISION_FAILED
                order.provision_message = str(exc)[:500]
                self._session.add(order)
                await orders_repo.save(order)
                await self._session.commit()
                logger.info(
                    "[DOMAIN_REGISTRATION_PERSISTENCE] Updated DomainRegistrationOrder status=PROVISION_FAILED committed to DB: order_id=%s, domain=%s",
                    order.id, domain,
                )

        st = order.status.value if hasattr(order.status, "value") else str(order.status)
        st_upper = st.upper()
        provision_success = st_upper in ("ACTIVE", "REGISTRATION_PENDING")
        return {
            "type": "DOMAIN_REGISTRATION",
            "domain": domain,
            "registrationOrderId": str(order.id),
            "batchId": str(batch_id) if batch_id else None,
            "periodYears": period,
            "status": st,
            "success": True,
            "provisionSuccess": provision_success,
            "error": None if provision_success else (order.provision_message or st),
            "message": order.provision_message,
            "openproviderDomainId": order.open_provider_domain_id,
            "isPremium": bool(getattr(order, "is_premium", False)),
        }

    async def _complete_domain_purchase(
        self,
        item: CartItem,
        buyer: AppUser,
        razorpay_payment_id: str,
        buyer_name: str,
        buyer_email: str,
        buyer_phone: str,
    ) -> dict[str, Any]:
        from app.repository.domain_listing_repository import DomainListingRepository

        repo = DomainListingRepository(self._session)
        listing = await repo.get_by_id(item.product_id)
        if listing is None:
            raise AppException("Domain listing not found during checkout.")

        listing.domain_status = DomainListingStatus.SOLD
        listing.payment_status = MarketplacePaymentStatus.COMPLETED
        listing.razorpay_payment_id = razorpay_payment_id
        listing.purchased_by_user_id = buyer.id
        listing.sold_at = datetime.now(timezone.utc)
        listing.purchase_buyer_name = buyer_name or None
        listing.purchase_buyer_email = buyer_email or None
        listing.purchase_buyer_phone = buyer_phone or None
        listing.purchase_addon_services = item.addon_services or None
        await repo.save(listing)

        await create_addon_operations_requests(
            self._session,
            user_id=buyer.id,
            buyer_name=buyer_name,
            buyer_email=buyer_email,
            buyer_phone=buyer_phone,
            addon_services_csv=item.addon_services,
        )

        from app.service.domain.domain_marketplace_transaction_service import (
            DomainMarketplaceTransactionService,
        )
        from app.service.domain.tax_invoice_number_service import ensure_tax_invoice_number
        from app.utils.domain_gst import domain_price_breakdown

        rzp_order_id = str((item.metadata_json or {}).get("_checkout_razorpay_order_id") or "")
        asking_price = float(listing.asking_price or 0.0)
        listing_tax = domain_price_breakdown(asking_price, years=1) if asking_price > 0 else None
        if listing_tax is not None:
            subtotal = float(listing_tax["subtotalInr"])
            gst = float(listing_tax["gstInr"])
            total_paid = float(listing_tax["totalInr"])
        else:
            meta = item.metadata_json or {}
            subtotal = float(meta.get("_checkout_subtotal_inr") or asking_price)
            gst = float(meta.get("_checkout_gst_inr") or 0.0)
            total_paid = float(meta.get("_checkout_total_inr") or (subtotal + gst))

        tx_id = None
        if listing.listed_by_user_id is not None:
            tx_service = DomainMarketplaceTransactionService(self._session)
            tx = await tx_service.create_from_payment(
                listing,
                buyer=buyer,
                razorpay_order_id=rzp_order_id,
                razorpay_payment_id=razorpay_payment_id,
                gross_amount_inr=asking_price,
            )
            tx_id = str(tx.id)

        from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
        from app.utils.registration_enums import RegistrationOrderStatus

        domain_order = DomainRegistrationOrder(
            domain_name=listing.domain_name or str(item.product_id),
            domain_extension=listing.domain_extension or ".com",
            buyer_id=buyer.id,
            buyer_full_name=buyer_name or f"{buyer.firstname or ''} {buyer.lastname or ''}".strip() or buyer.email or "",
            buyer_email=buyer_email or buyer.email or "",
            buyer_phone=buyer_phone or buyer.phone_number or "",
            street="Main Street",
            city="Hubli",
            state="Karnataka",
            zip_code="580001",
            country="IN",
            period_years=1,
            subtotal_inr=subtotal or asking_price,
            gst_inr=gst,
            price_inr=total_paid or asking_price,
            quoted_unit_price_inr=asking_price,
            price_source="marketplace",
            status=RegistrationOrderStatus.ACTIVE,
            razorpay_order_id=rzp_order_id or None,
            razorpay_payment_id=razorpay_payment_id,
            provision_message="Marketplace domain purchase completed.",
            provision_attempts=1,
        )
        self._session.add(domain_order)
        await self._session.flush()
        await ensure_tax_invoice_number(self._session, domain_order)
        await self._session.flush()

        return {
            "type": "DOMAIN_LISTING",
            "domainId": str(item.product_id),
            "registrationOrderId": str(domain_order.id),
            "transactionId": tx_id,
        }

    async def _complete_technology_purchase(
        self,
        item: CartItem,
        buyer: AppUser,
        razorpay_payment_id: str,
        buyer_name: str,
        buyer_email: str,
        buyer_phone: str,
    ) -> dict[str, Any]:
        from app.entity.cocreation.software_entity import Software
        from app.entity.cocreation.technology_pricing_plan_entity import TechnologyPricingPlan
        from app.entity.technology_services.technology_service_entity import TechnologyServiceEntity
        from app.entity.technology_services.technology_subscription_entity import TechnologySubscriptionEntity
        from app.entity.technology_services.technology_subscription_invoice_entity import TechnologySubscriptionInvoiceEntity
        from app.integrations.resellportal.client import get_resellportal_client
        from app.repository.software_purchase_repository import SoftwarePurchaseRepository
        from app.repository.cobrother_request_repository import CoBrotherRequestRepository
        from app.service.auth.mail_service import MailService
        from sqlalchemy import select as sa_select
        from sqlalchemy.orm import selectinload as sa_selectinload

        purchase_repo = SoftwarePurchaseRepository(self._session)
        cobrother_repo = CoBrotherRequestRepository(self._session)

        meta = item.metadata_json or {}
        service_slug = str(meta.get("serviceSlug") or "").strip().lower()
        result_status = None
        result_success = False
        subscriber_id = None

        # Idempotency for technology-service subscriptions (e.g. AI Business Suite
        # via the fallback seed UUID has no SoftwarePurchase row, so the check
        # below would miss it — check the subscription first).
        if service_slug:
            existing_sub_stmt = sa_select(TechnologySubscriptionEntity).where(
                TechnologySubscriptionEntity.user_id == str(buyer.id),
                TechnologySubscriptionEntity.service_slug == service_slug,
                TechnologySubscriptionEntity.provider_order_id.is_not(None),
            )
            existing_sub_result = await self._session.execute(existing_sub_stmt)
            existing_sub = existing_sub_result.scalar_one_or_none()
            if existing_sub is not None:
                existing_payment_purchase = await purchase_repo.get_by_razorpay_payment_id(razorpay_payment_id)
                result_status = existing_sub.status
                result_success = existing_sub.status == "ACTIVE"
                subscriber_id = str(existing_sub.id)
                return {
                    "type": "TECHNOLOGY",
                    "purchaseId": str(existing_payment_purchase.id) if existing_payment_purchase else None,
                    "softwareId": str(item.product_id),
                    "alreadyProcessed": True,
                    "subscriptionId": str(existing_sub.id),
                    "providerOrderId": existing_sub.provider_order_id,
                    "status": existing_sub.status,
                }

        existing_payment_purchase = await purchase_repo.get_by_razorpay_payment_id(razorpay_payment_id)
        if (
            existing_payment_purchase is not None
            and existing_payment_purchase.payment_status == SoftwarePaymentStatus.COMPLETED
            and service_slug
        ):
            existing_subscription_stmt = sa_select(TechnologySubscriptionEntity).where(
                TechnologySubscriptionEntity.user_id == str(buyer.id),
                TechnologySubscriptionEntity.service_slug == service_slug,
                TechnologySubscriptionEntity.provider_order_id.is_not(None),
            )
            existing_subscription_result = await self._session.execute(existing_subscription_stmt)
            existing_subscription = existing_subscription_result.scalar_one_or_none()
            if existing_subscription is not None:
                result_status = existing_subscription.status
                result_success = existing_subscription.status == "ACTIVE"
                subscriber_id = str(existing_subscription.id)
                return {
                    "type": "TECHNOLOGY",
                    "purchaseId": str(existing_payment_purchase.id),
                    "softwareId": str(item.product_id),
                    "alreadyProcessed": True,
                    "subscriptionId": str(existing_subscription.id),
                    "providerOrderId": existing_subscription.provider_order_id,
                    "status": existing_subscription.status,
                }

        stmt = (
            sa_select(Software)
            .where(Software.id == item.product_id, Software.is_deleted.is_(False))
            .options(sa_selectinload(Software.pricing_plans))
        )
        result = await self._session.execute(stmt)
        software = result.scalar_one_or_none()

        if software is None:
            # Fall back: provider-powered service from technology_services_catalogue.
            tech_service = await self._cart_service._get_technology_service(item.product_id)
            if tech_service is None:
                tech_service = await self._cart_service._get_technology_service_fallback(item.product_id)
        else:
            tech_service = None

        if software is None and tech_service is None:
            raise AppException("Technology listing not found during checkout.")

        base_price = 0.0
        seller_price = None
        platform_fee = 0.0
        seller_payout = 0.0
        plan_enum = None
        purchase = None

        if software is not None:
            base_price = float(software.price or 0)
            seller_price = software.seller_price

            if item.selected_plan:
                key_mapping = {
                    "1_MONTH": "ONE_MONTH",
                    "3_MONTHS": "THREE_MONTHS",
                    "6_MONTHS": "SIX_MONTHS",
                    "12_MONTHS": "TWELVE_MONTHS",
                }
                mapped = key_mapping.get(item.selected_plan, item.selected_plan)
                try:
                    plan_enum = TechnologyPricingPlanDuration(mapped)
                except ValueError:
                    pass
                if software.pricing_plans and plan_enum:
                    plan = next((p for p in software.pricing_plans if p.plan_duration == plan_enum and p.is_active), None)
                    if plan:
                        base_price = float(plan.price)

            is_software = software.technology_type == TechnologyType.SOFTWARE
            is_subscription = plan_enum is not None and plan_enum != TechnologyPricingPlanDuration.ONE_TIME
            if is_software and is_subscription:
                platform_fee = base_price
                seller_payout = 0.0
            else:
                seller_payout = float(seller_price) if seller_price is not None else 0.0
                platform_fee = round(base_price - seller_payout, 2)

            now = datetime.now(timezone.utc)
            purchase = SoftwarePurchase(
                software_id=item.product_id,
                buyer_id=buyer.id,
                buyer_full_name=buyer_name,
                buyer_email=buyer_email,
                buyer_phone=buyer_phone,
                purchase_addon_services=item.addon_services or None,
                razorpay_order_id=(item.metadata_json or {}).get("_checkout_razorpay_order_id", ""),
                razorpay_payment_id=razorpay_payment_id,
                payment_status=SoftwarePaymentStatus.COMPLETED,
                completion_status=SoftwarePurchaseCompletionStatus.CONFIRMED,
                co_brother_opt_in=item.co_brother_opt_in,
                co_brother_help_paid=item.co_brother_opt_in,
                sold_at=now,
                selected_plan=plan_enum,
                gross_amount_inr=base_price,
                platform_fee_inr=platform_fee,
                seller_payout_inr=seller_payout,
            )

            if plan_enum:
                if plan_enum == TechnologyPricingPlanDuration.ONE_MONTH:
                    purchase.expiry_date = now + timedelta(days=30)
                elif plan_enum == TechnologyPricingPlanDuration.THREE_MONTHS:
                    purchase.expiry_date = now + timedelta(days=90)
                elif plan_enum == TechnologyPricingPlanDuration.SIX_MONTHS:
                    purchase.expiry_date = now + timedelta(days=180)
                elif plan_enum == TechnologyPricingPlanDuration.TWELVE_MONTHS:
                    purchase.expiry_date = now + timedelta(days=365)

            await purchase_repo.create(purchase)

            software.software_status = SoftwareStatus.SOLD
            await self._session.flush()

            req = CoBrotherRequest(
                request_type=CoBrotherRequestType.COCREATION,
                entity_id=purchase.id,
                entity_snapshot=software.name,
                lister_id=purchase.buyer_id,
                status=CoBrotherRequestStatus.PENDING,
            )
            await cobrother_repo.create(req)
        else:
            # ── TechnologyServiceEntity path ──
            # Provider-powered services (AI Business Suite etc.) live in
            # technology_services_catalogue and are provisioned via ResellPortal.
            # No SoftwarePurchase row is created (its FK targets software_listings).
            plans_json = getattr(tech_service, "plans_json", None) if not isinstance(tech_service, dict) else tech_service.get("plans_json")
            override_monthly = getattr(tech_service, "price_override_monthly", None) if not isinstance(tech_service, dict) else tech_service.get("price_override_monthly")
            override_annually = getattr(tech_service, "price_override_annually", None) if not isinstance(tech_service, dict) else tech_service.get("price_override_annually")

            base_price = CartService._tech_service_plan_price_inr(
                plans_json,
                item.selected_plan,
                meta,
                override_monthly=override_monthly,
                override_annually=override_annually,
            )
            seller_payout = 0.0
            platform_fee = round(base_price - seller_payout, 2)

            req = CoBrotherRequest(
                request_type=CoBrotherRequestType.COCREATION,
                entity_id=item.product_id,
                entity_snapshot=getattr(tech_service, "name", None) if not isinstance(tech_service, dict) else tech_service.get("name"),
                lister_id=buyer.id,
                razorpay_order_id=(item.metadata_json or {}).get("_checkout_razorpay_order_id", ""),
                razorpay_payment_id=razorpay_payment_id,
                status=CoBrotherRequestStatus.PENDING,
            )
            await cobrother_repo.create(req)

        product_name = str(
            (item.metadata_json or {}).get("productName")
            or (software.name if software is not None else (
                getattr(tech_service, "name", None)
                if not isinstance(tech_service, dict)
                else tech_service.get("name", "")
            ))
            or ""
        ).strip()

        # ------------------------------------------------------------------ #
        # Marketplace software path (Azure etc.) — no provider provisioning. #
        # The SoftwarePurchase record above IS the fulfillment. Never create  #
        # a technology subscription for it.                                   #
        # ------------------------------------------------------------------ #
        if software is not None:
            await create_addon_operations_requests(
                self._session,
                user_id=buyer.id,
                buyer_name=buyer_name,
                buyer_email=buyer_email,
                buyer_phone=buyer_phone,
                addon_services_csv=item.addon_services,
            )
            return {
                "type": "TECHNOLOGY",
                "purchaseId": str(purchase.id) if purchase is not None else None,
                "softwareId": str(item.product_id),
                "githubLink": software.github_link or "",
            }

        # ------------------------------------------------------------------ #
        # TechnologyServiceEntity path — provider-powered catalogue services. #
        # Only services with a confirmed provider_product_key are processed #
        # here; everything else falls through with the CoBrotherRequest     #
        # created above (manual fulfillment path).                           #
        # ------------------------------------------------------------------ #
        provider_product_key = None
        provider_service_slug = None
        provider_service_name = product_name

        if tech_service is not None and not isinstance(tech_service, dict):
            provider_product_key = getattr(tech_service, "provider_product_key", None) or get_product_key(
                getattr(tech_service, "slug", "")
            )
            provider_service_slug = getattr(tech_service, "slug", None)
        elif tech_service is not None and isinstance(tech_service, dict):
            provider_product_key = tech_service.get("provider_product_key") or get_product_key(tech_service.get("slug", ""))
            provider_service_slug = tech_service.get("slug")

        if not provider_service_slug:
            raise AppException("Technology service slug could not be resolved during checkout.")

        provider_plan_code = str(item.selected_plan or "starter").strip() or "starter"
        billing_cycle = "monthly"
        bc_meta = (item.metadata_json or {}).get("billingCycle", "").lower()
        if bc_meta.startswith("ann"):
            billing_cycle = "annually"

        razorpay_order_id = str((item.metadata_json or {}).get("_checkout_razorpay_order_id") or "").strip() or None
        now_utc = datetime.now(timezone.utc)
        period_days = 365 if billing_cycle == "annually" else 30

        # ── 1) CREATE subscription + invoice + CoBrotherRequest, then COMMIT  ──
        #     BEFORE any provider call. A successful payment must NEVER
        #     disappear because ResellPortal provisioning failed.
        sub = TechnologySubscriptionEntity(
            user_id=str(buyer.id),
            service_slug=provider_service_slug,
            service_name=provider_service_name or provider_service_slug,
            plan_code=provider_plan_code,
            billing_cycle=billing_cycle,
            price=base_price,
            currency="INR",
            status="PAYMENT_CAPTURED",
            payment_status="CAPTURED",
            idempotency_key=str(uuid.uuid4()),
            provision_attempts=0,
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            auto_renew=True,
            email_sent=False,
            confirmation_sent=False,
            needs_review=False,
        )
        self._session.add(sub)
        await self._session.flush()

        invoice_number = f"INV-CB-{uuid.uuid4().hex[:8].upper()}"
        invoice = TechnologySubscriptionInvoiceEntity(
            subscription_id=str(sub.id),
            user_id=str(buyer.id),
            invoice_number=invoice_number,
            amount=float(base_price),
            currency="INR",
            status="PAID",
            billing_period_start=now_utc,
            billing_period_end=now_utc + timedelta(days=period_days),
            payment_method="Razorpay",
        )
        self._session.add(invoice)
        await self._session.flush()

        # Persist payment → subscription → invoice → CoBrotherRequest before
        # touching the provider.
        await self._session.commit()

        cobrother_request_id = str(req.id)
        subscriber_id = str(sub.id)
        purchase_date = now_utc.strftime("%d %b %Y")
        purchases_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/purchases"
        plan_name = provider_plan_code.replace("_", " ").title()
        result_status = "PAYMENT_CAPTURED"
        result_success = True

        max_retries = max(1, int(settings.TECH_SUBSCRIPTION_MAX_RETRIES))

        if provider_product_key and is_provider_mapped(provider_service_slug):
            # ── 2) Validate required customer input BEFORE any provider call ──
            # Business Phone needs areaCode/phoneNumber; Web Hosting needs a
            # primary domain. If missing, do NOT call POST /orders — put the
            # paid purchase into a needs-input state instead.
            ok, missing = validate_order_input(provider_service_slug, item.metadata_json or {})
            if not ok:
                sub.status = "PENDING"
                sub.needs_review = True
                sub.last_provider_status = "NEEDS_INPUT"
                sub.last_provider_error = (
                    f"{provider_service_name} requires: {', '.join(missing)}. "
                    "Please provide the required information to activate."
                )
                sub.next_retry_at = None
                await self._session.flush()
                result_status = "PENDING"
                result_success = False
                subscriber_id = str(sub.id)
                if not sub.email_sent:
                    try:
                        await MailService.send_technology_purchase_pending_email(
                            to_email=buyer_email,
                            customer_name=buyer_name,
                            service_name=provider_service_name or provider_service_slug,
                            plan_name=plan_name,
                            billing_cycle=billing_cycle,
                            cobrother_order_id=cobrother_request_id,
                            razorpay_payment_id=razorpay_payment_id,
                            amount_inr=float(base_price),
                            purchase_date=purchase_date,
                            reason=sub.last_provider_error,
                            purchases_url=purchases_url,
                        )
                        sub.email_sent = True
                        await self._session.flush()
                    except Exception:
                        logger.exception("cart.checkout.technology.needs_input_email.failed purchase=%s", item.product_id)
            else:
                client = get_resellportal_client()

                # ── 3) Reconcile existing provider orders FIRST ──
                # POST /orders has NO idempotency, so before creating a new
                # order we look for an existing matching order via GET /orders.
                reconciliation = client.reconcile_pending_provisioning(
                    service_slug=provider_service_slug,
                    user_id=str(buyer.id),
                    product_key=provider_product_key,
                    user_email=buyer_email,
                    plan_code=provider_plan_code,
                    billing_cycle=billing_cycle,
                )
                if reconciliation.get("reconciled") and reconciliation.get("provider_order_id"):
                    # Adopt the existing provider order — never create a duplicate.
                    sub.provider_order_id = reconciliation.get("provider_order_id")
                    sub.provider_subscription_id = reconciliation.get("provider_subscription_id")
                    sub.last_provider_status = str(reconciliation.get("status") or "PENDING").upper()
                    if str(reconciliation.get("status") or "").upper() == "ACTIVE":
                        sub.status = "ACTIVE"
                        sub.next_retry_at = None
                        sub.needs_review = False
                        sub.last_provider_error = None
                        if sub.current_period_start is None or sub.current_period_end is None:
                            sub.current_period_start, sub.current_period_end = _tech_sub_periods(billing_cycle)
                        await self._session.flush()
                        result_status = "ACTIVE"
                        result_success = True
                        subscriber_id = str(sub.id)
                        if not sub.email_sent:
                            try:
                                await MailService.send_technology_purchase_confirmation_email(
                                    to_email=buyer_email,
                                    customer_name=buyer_name,
                                    service_name=provider_service_name or provider_service_slug,
                                    plan_name=plan_name,
                                    billing_cycle=billing_cycle,
                                    cobrother_order_id=cobrother_request_id,
                                    razorpay_payment_id=razorpay_payment_id,
                                    amount_inr=float(base_price),
                                    purchase_date=purchase_date,
                                    service_status="Active",
                                    provider_info=f"Service ID: {sub.provider_subscription_id or sub.provider_order_id or 'N/A'}",
                                    purchases_url=purchases_url,
                                )
                                sub.email_sent = True
                                sub.confirmation_sent = True
                                await self._session.flush()
                            except Exception:
                                logger.exception("cart.checkout.technology.confirmation_email.failed purchase=%s", item.product_id)
                    else:
                        sub.status = "PENDING"
                        sub.next_retry_at = datetime.now(timezone.utc) + _tech_backoff_for(1)
                        await self._session.flush()
                        result_status = "PENDING"
                        result_success = False
                        subscriber_id = str(sub.id)
                        if not sub.email_sent:
                            try:
                                await MailService.send_technology_purchase_pending_email(
                                    to_email=buyer_email,
                                    customer_name=buyer_name,
                                    service_name=provider_service_name or provider_service_slug,
                                    plan_name=plan_name,
                                    billing_cycle=billing_cycle,
                                    cobrother_order_id=cobrother_request_id,
                                    razorpay_payment_id=razorpay_payment_id,
                                    amount_inr=float(base_price),
                                    purchase_date=purchase_date,
                                    reason="Your provider order was found and is still being activated. Activation will continue automatically — you will receive a confirmation email once your service is active.",
                                    purchases_url=purchases_url,
                                )
                                sub.email_sent = True
                                await self._session.flush()
                            except Exception:
                                logger.exception("cart.checkout.technology.pending_email.failed purchase=%s", item.product_id)
                else:
                    # ── 4) No existing order → provision via POST /orders ──
                    order_parameters = build_order_parameters(
                        product_key=provider_product_key,
                        plan_code=provider_plan_code,
                        billing_cycle=billing_cycle,
                        metadata=item.metadata_json or {},
                    )
                    sub.status = "PROVISIONING"
                    sub.last_provision_attempt_at = datetime.now(timezone.utc)
                    sub.provision_attempts += 1
                    sub.last_provider_status = None
                    sub.last_provider_error = None
                    await self._session.flush()

                    prov_res = client.provision_service(
                        service_slug=provider_service_slug,
                        service_name=provider_service_name or provider_service_slug,
                        plan_code=provider_plan_code,
                        billing_cycle=billing_cycle,
                        user_email=buyer_email,
                        user_id=str(buyer.id),
                        product_key=provider_product_key,
                        order_parameters=order_parameters,
                    )

                    provider_success = prov_res.get("success") is True
                    provider_status = str(prov_res.get("status") or "PENDING").upper()
                    sub.last_provider_status = provider_status
                    sub.last_provider_error = str(prov_res.get("error") or "") if not provider_success else None

                    if provider_success and provider_status == "ACTIVE":
                        sub.status = "ACTIVE"
                        sub.provider_order_id = prov_res.get("provider_order_id")
                        sub.provider_subscription_id = prov_res.get("provider_subscription_id")
                        sub.credentials_json = json.dumps(prov_res.get("credentials") or {})
                        start, end = prov_res.get("current_period_start"), prov_res.get("current_period_end")
                        if start is None or end is None:
                            start, end = _tech_sub_periods(billing_cycle)
                        sub.current_period_start = start
                        sub.current_period_end = end
                        sub.next_retry_at = None
                        sub.needs_review = False
                        sub.last_provider_error = None
                        await self._session.flush()
                        result_status = "ACTIVE"
                        result_success = True
                        subscriber_id = str(sub.id)
                        if not sub.email_sent:
                            try:
                                await MailService.send_technology_purchase_confirmation_email(
                                    to_email=buyer_email,
                                    customer_name=buyer_name,
                                    service_name=provider_service_name or provider_service_slug,
                                    plan_name=plan_name,
                                    billing_cycle=billing_cycle,
                                    cobrother_order_id=cobrother_request_id,
                                    razorpay_payment_id=razorpay_payment_id,
                                    amount_inr=float(base_price),
                                    purchase_date=purchase_date,
                                    service_status="Active",
                                    provider_info=f"Service ID: {prov_res.get('service_id', 'N/A')}",
                                    purchases_url=purchases_url,
                                )
                                sub.email_sent = True
                                sub.confirmation_sent = True
                                await self._session.flush()
                            except Exception:
                                logger.exception("cart.checkout.technology.confirmation_email.failed purchase=%s", item.product_id)
                    elif provider_success and provider_status in ("PENDING", "PROVISIONING_PENDING"):
                        sub.status = "PENDING"
                        sub.provider_order_id = prov_res.get("provider_order_id")
                        sub.provider_subscription_id = prov_res.get("provider_subscription_id")
                        if prov_res.get("credentials"):
                            sub.credentials_json = json.dumps(prov_res.get("credentials"))
                        sub.next_retry_at = datetime.now(timezone.utc) + _tech_backoff_for(sub.provision_attempts)
                        await self._session.flush()
                        result_status = "PENDING"
                        result_success = False
                        subscriber_id = str(sub.id)
                        if not sub.email_sent:
                            try:
                                await MailService.send_technology_purchase_pending_email(
                                    to_email=buyer_email,
                                    customer_name=buyer_name,
                                    service_name=provider_service_name or provider_service_slug,
                                    plan_name=plan_name,
                                    billing_cycle=billing_cycle,
                                    cobrother_order_id=cobrother_request_id,
                                    razorpay_payment_id=razorpay_payment_id,
                                    amount_inr=float(base_price),
                                    purchase_date=purchase_date,
                                    reason="Provider provisioning is pending. Activation will be retried automatically — you will receive a confirmation email once your service is active.",
                                    purchases_url=purchases_url,
                                )
                                sub.email_sent = True
                                await self._session.flush()
                            except Exception:
                                logger.exception("cart.checkout.technology.pending_email.failed purchase=%s", item.product_id)
                    else:
                        sub.status = "PROVISIONING_FAILED"
                        sub.last_provider_error = str(
                            prov_res.get("error") or prov_res.get("message") or "Provider provisioning failed."
                        )
                        if sub.provision_attempts >= max_retries:
                            sub.needs_review = True
                            sub.next_retry_at = None
                        else:
                            sub.next_retry_at = datetime.now(timezone.utc) + _tech_backoff_for(sub.provision_attempts)
                        await self._session.flush()
                        result_status = "PROVISIONING_FAILED"
                        result_success = False
                        subscriber_id = str(sub.id)
                        if not sub.email_sent:
                            try:
                                await MailService.send_technology_purchase_failed_email(
                                    to_email=buyer_email,
                                    customer_name=buyer_name,
                                    service_name=provider_service_name or provider_service_slug,
                                    plan_name=plan_name,
                                    billing_cycle=billing_cycle,
                                    cobrother_order_id=cobrother_request_id,
                                    razorpay_payment_id=razorpay_payment_id,
                                    amount_inr=float(base_price),
                                    purchase_date=purchase_date,
                                    reason=sub.last_provider_error,
                                    purchases_url=purchases_url,
                                )
                                sub.email_sent = True
                                await self._session.flush()
                            except Exception:
                                logger.exception("cart.checkout.technology.failed_email.failed purchase=%s", item.product_id)
        else:
            # ── Manual fulfillment path (e.g. WordPress Plugin Pack) ──
            # No provider mapping / product key: NEVER call POST /orders and
            # never fake a provider ID. Admin fulfills via the admin endpoint
            # and the subscription transitions PENDING → ACTIVE.
            sub.status = "PENDING"
            sub.needs_review = True
            sub.last_provider_status = "MANUAL_FULFILLMENT_REQUIRED"
            sub.last_provider_error = "This service has no automated provider mapping. Manual fulfillment required."
            sub.next_retry_at = None
            sub.provision_attempts = max_retries  # exclude from auto retry worker
            await self._session.flush()
            result_status = "PENDING"
            result_success = False
            subscriber_id = str(sub.id)
            if not sub.email_sent:
                try:
                    await MailService.send_technology_purchase_pending_email(
                        to_email=buyer_email,
                        customer_name=buyer_name,
                        service_name=provider_service_name or product_name,
                        plan_name=plan_name,
                        billing_cycle=billing_cycle,
                        cobrother_order_id=cobrother_request_id,
                        razorpay_payment_id=razorpay_payment_id,
                        amount_inr=float(base_price),
                        purchase_date=purchase_date,
                        reason="Payment received. This service is fulfilled manually by our team — activation will complete shortly. No further charge.",
                        purchases_url=purchases_url,
                    )
                    sub.email_sent = True
                    await self._session.flush()
                except Exception:
                    logger.exception("cart.checkout.technology.manual_pending_email.failed purchase=%s", item.product_id)

        await create_addon_operations_requests(
            self._session,
            user_id=buyer.id,
            buyer_name=buyer_name,
            buyer_email=buyer_email,
            buyer_phone=buyer_phone,
            addon_services_csv=item.addon_services,
        )

        return {
            "type": "TECHNOLOGY",
            "purchaseId": str(purchase.id) if purchase is not None else None,
            "softwareId": str(item.product_id),
            "githubLink": software.github_link or "" if software is not None else "",
            # Provider-powered technology services must be filed under
            # Technology Services with their real provisioning status.
            "isService": tech_service is not None,
            "status": result_status,
            "success": result_success,
            "subscriptionId": subscriber_id,
            "providerSubscriptionId": sub.provider_subscription_id,
            "providerOrderId": sub.provider_order_id,
        }

    async def _complete_venture_purchase(
        self,
        item: CartItem,
        buyer: AppUser,
        razorpay_payment_id: str,
    ) -> dict[str, Any]:
        from app.entity.coventure.venture_deal_transaction_entity import VentureDealTransaction
        from app.utils.venture_enums import VentureDealKind, VentureDealStatus
        from app.utils.transfer_enums import MarketplaceEscrowStatus
        from app.entity.coventure.venture_entity import Venture
        from app.service.platform.listing_pricing_service import ListingPricingService
        from sqlalchemy import select

        stmt = select(Venture).where(Venture.id == item.product_id)
        result = await self._session.execute(stmt)
        venture = result.scalar_one_or_none()
        if venture is None:
            raise AppException("Venture not found during checkout.")

        brand = venture.brand_details if hasattr(venture, "brand_details") else None
        gross = float(brand.deal_value or 0) if brand and hasattr(brand, "deal_value") else 0.0

        pricing = ListingPricingService(self._session)
        pct = await pricing.acquisition_commission_percent()
        platform_fee = round(gross * pct / 100, 2)
        seller_payout = round(gross - platform_fee, 2)

        seller_id = venture.listed_by_user_id

        tx = VentureDealTransaction(
            venture_id=item.product_id,
            buyer_id=buyer.id,
            seller_id=seller_id,
            deal_kind=VentureDealKind.FULL_ACQUISITION,
            deal_status=VentureDealStatus.ESCROW_HELD,
            escrow_status=MarketplaceEscrowStatus.HELD,
            gross_amount_inr=gross,
            platform_fee_inr=platform_fee,
            seller_payout_inr=seller_payout,
            razorpay_order_id=(item.metadata_json or {}).get("_checkout_razorpay_order_id", ""),
            razorpay_payment_id=razorpay_payment_id,
        )
        self._session.add(tx)
        await self._session.flush()

        venture.purchased_by_user_id = buyer.id
        await self._session.flush()

        return {
            "type": "VENTURE_DEAL",
            "ventureId": str(item.product_id),
            "transactionId": str(tx.id),
        }
