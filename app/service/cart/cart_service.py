"""Cart business logic — add, remove, get, validate, resolve prices."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.config import settings
from app.entity.cart.cart_item_entity import CartItem
from app.entity.cobranding.domain_listing_entity import DomainListing
from app.entity.cocreation.software_entity import Software
from app.entity.coventure.venture_entity import Venture
from app.entity.technology_services.technology_service_entity import TechnologyServiceEntity
from app.repository.cart_item_repository import CartItemRepository
from app.schemas.cart_schemas import (
    AddToCartRequest,
    CartItemResponse,
    CartResponse,
    UpdateCartItemRequest,
)
from app.utils.addon_services import ADDON_PRICES
from app.utils.cart_enums import CartProductType
from app.utils.domain_gst import domain_price_breakdown
from app.utils.cocreation_enums import SoftwareStatus, SoftwarePurchaseType
from app.utils.marketplace_enums import DomainListingStatus
from app.utils.venture_enums import VentureListingStatus
from app.service.domain.domain_enquiry_service import (
    DOMAIN_UNAVAILABLE_MSG,
    is_premium_marketplace_listing,
)
from app.service.domain.managed_acquisition_pricing import (
    is_openprovider_managed_registration,
)

logger = logging.getLogger(__name__)

COBROTHER_FEE_INR = 1000.0

# Client-supplied cart metadata must never set checkout/fulfillment control keys.
_RESERVED_CART_METADATA_PREFIXES = ("_checkout_", "_fulfilled_")


def _sanitize_client_cart_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    cleaned: dict[str, Any] = {}
    for key, value in metadata.items():
        k = str(key)
        if any(k.startswith(prefix) for prefix in _RESERVED_CART_METADATA_PREFIXES):
            continue
        cleaned[k] = value
    return cleaned


class CartService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = CartItemRepository(session)

    async def add_item(
        self,
        user_id: uuid.UUID,
        req: AddToCartRequest,
    ) -> CartItemResponse:
        await self.cleanup_stale_purchased_cart_items(user_id)
        existing = await self._repo.get_by_user_and_product(
            user_id, req.product_type, req.product_id
        )
        if existing:
            await self._validate_product_available(
                req.product_type, req.product_id, user_id, req.metadata
            )
            await self._enforce_managed_acquisition_cart_rules(
                user_id,
                req.product_type,
                req.product_id,
                metadata=req.metadata or existing.metadata_json,
                updating_existing=True,
            )
            existing.selected_plan = req.selected_plan or existing.selected_plan
            existing.addon_services = (
                ",".join(req.addon_services) if req.addon_services else existing.addon_services
            )
            existing.co_brother_opt_in = req.co_brother_opt_in
            if req.metadata:
                existing.metadata_json = _sanitize_client_cart_metadata(req.metadata)
            # Tag premium marketplace lines for FE confirm flow.
            if req.product_type == CartProductType.DOMAIN_LISTING:
                listing = await self._get_domain_listing(req.product_id)
                if listing is not None and is_premium_marketplace_listing(listing):
                    meta = dict(existing.metadata_json or {})
                    meta["isPremiumMarketplace"] = True
                    existing.metadata_json = meta
            elif req.product_type == CartProductType.DOMAIN_REGISTRATION:
                meta = dict(existing.metadata_json or {})
                if is_openprovider_managed_registration(meta):
                    meta["isManagedAcquisition"] = True
                    existing.metadata_json = meta
            await self._repo.save(existing)
            return await self._build_item_response(existing)

        await self._validate_product_available(
            req.product_type, req.product_id, user_id, req.metadata
        )
        await self._enforce_managed_acquisition_cart_rules(
            user_id,
            req.product_type,
            req.product_id,
            metadata=req.metadata,
            updating_existing=False,
        )

        metadata = _sanitize_client_cart_metadata(req.metadata)
        if req.product_type == CartProductType.DOMAIN_LISTING:
            listing = await self._get_domain_listing(req.product_id)
            if listing is not None and is_premium_marketplace_listing(listing):
                metadata["isPremiumMarketplace"] = True
        elif req.product_type == CartProductType.DOMAIN_REGISTRATION:
            if is_openprovider_managed_registration(metadata):
                metadata["isManagedAcquisition"] = True

        item = CartItem(
            user_id=user_id,
            product_type=req.product_type,
            product_id=req.product_id,
            quantity=1,
            selected_plan=req.selected_plan,
            addon_services=",".join(req.addon_services) if req.addon_services else None,
            co_brother_opt_in=req.co_brother_opt_in,
            metadata_json=metadata or None,
        )
        await self._repo.create(item)
        return await self._build_item_response(item)

    async def _enforce_managed_acquisition_cart_rules(
        self,
        user_id: uuid.UUID,
        product_type: CartProductType,
        product_id: uuid.UUID,
        *,
        metadata: dict[str, Any] | None = None,
        updating_existing: bool,
    ) -> None:
        """Marketplace premium + OP managed registration (> ₹5L) must checkout alone."""
        cart_items = await self._repo.get_by_user(user_id)

        async def _is_premium_listing_item(it: CartItem) -> bool:
            if it.product_type != CartProductType.DOMAIN_LISTING:
                return False
            listing = await self._get_domain_listing(it.product_id)
            return listing is not None and is_premium_marketplace_listing(listing)

        def _is_managed_reg_item(it: CartItem) -> bool:
            return (
                it.product_type == CartProductType.DOMAIN_REGISTRATION
                and is_openprovider_managed_registration(it.metadata_json)
            )

        premium_listing_in_cart: list[CartItem] = []
        managed_reg_in_cart: list[CartItem] = []
        for it in cart_items:
            if await _is_premium_listing_item(it):
                premium_listing_in_cart.append(it)
            elif _is_managed_reg_item(it):
                managed_reg_in_cart.append(it)

        adding_premium_listing = False
        if product_type == CartProductType.DOMAIN_LISTING:
            listing = await self._get_domain_listing(product_id)
            adding_premium_listing = (
                listing is not None and is_premium_marketplace_listing(listing)
            )

        adding_managed_reg = (
            product_type == CartProductType.DOMAIN_REGISTRATION
            and is_openprovider_managed_registration(metadata)
        )

        if adding_premium_listing or adding_managed_reg:
            others = [
                it
                for it in cart_items
                if not (
                    it.product_type == product_type and it.product_id == product_id
                )
            ]
            if others:
                raise AppException(
                    "Premium domains above ₹5,00,000 use a dedicated managed acquisition "
                    "checkout and cannot be mixed with other cart items. "
                    "Please clear your cart first, then add this domain.",
                    status_code=400,
                    code="PREMIUM_CART_ALONE",
                )
            return

        # Adding a non-managed item while a managed acquisition line is present.
        if (premium_listing_in_cart or managed_reg_in_cart) and not updating_existing:
            raise AppException(
                "Your cart already holds a managed acquisition domain. "
                "Complete or remove that request before adding other items.",
                status_code=400,
                code="PREMIUM_CART_ALONE",
            )

    async def update_item(
        self,
        item_id: uuid.UUID,
        user_id: uuid.UUID,
        req: UpdateCartItemRequest,
    ) -> CartItemResponse:
        item = await self._repo.get_by_id(item_id)
        if item is None or item.user_id != user_id:
            raise AppException("Cart item not found.", status_code=404)

        if req.selected_plan is not None:
            item.selected_plan = req.selected_plan or None
        if req.addon_services is not None:
            item.addon_services = ",".join(req.addon_services) if req.addon_services else None
        if req.co_brother_opt_in is not None:
            item.co_brother_opt_in = req.co_brother_opt_in
        if req.metadata is not None:
            item.metadata_json = _sanitize_client_cart_metadata(req.metadata)

        await self._repo.save(item)
        return await self._build_item_response(item)

    async def remove_item(self, item_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        deleted = await self._repo.delete_by_id(item_id, user_id)
        if not deleted:
            raise AppException("Cart item not found.", status_code=404)
        await self._session.commit()
        return True

    async def clear_cart(self, user_id: uuid.UUID) -> int:
        count = await self._repo.clear_user_cart(user_id)
        await self._session.commit()
        return count

    async def update_domain_registration_period(
        self,
        user_id: uuid.UUID,
        period_years: int,
        *,
        item_id: uuid.UUID | None = None,
    ) -> CartResponse:
        """
        Re-quote DOMAIN_REGISTRATION line(s) for the selected period.

        When ``item_id`` is provided, only that cart line is updated (per-domain
        periods). When omitted, all registration lines are updated (legacy).
        """
        from app.integrations.openprovider.client import tld_min_registration_years
        from app.service.domain.domain_registration_service import DomainRegistrationService

        period_years = max(1, min(10, int(period_years or 1)))
        items = await self._repo.get_by_user(user_id)
        reg_items = [
            it for it in items if it.product_type == CartProductType.DOMAIN_REGISTRATION
        ]
        if not reg_items:
            raise AppException(
                "No domain registrations in cart to update.",
                status_code=400,
            )

        if item_id is not None:
            target = next((it for it in reg_items if it.id == item_id), None)
            if target is None:
                raise AppException(
                    "Domain registration cart item not found.",
                    status_code=404,
                )
            reg_items = [target]

        svc = DomainRegistrationService(self._session)
        for item in reg_items:
            await self._apply_registration_period_quote(
                item,
                period_years,
                svc=svc,
                tld_min_registration_years=tld_min_registration_years,
            )

        return await self.get_cart(user_id)

    async def _apply_registration_period_quote(
        self,
        item: CartItem,
        period_years: int,
        *,
        svc: Any,
        tld_min_registration_years: Any,
    ) -> None:
        """Live-quote one DOMAIN_REGISTRATION cart line and persist metadata."""
        meta = dict(item.metadata_json or {})
        domain = str(meta.get("domainName") or "").lower().strip()
        if not domain or "." not in domain:
            raise AppException(
                "A domain registration cart item is missing its domain name.",
                status_code=400,
            )
        tld = str(meta.get("tld") or domain.split(".", 1)[1]).lstrip(".")
        min_years = max(
            1,
            int(meta.get("minPeriodYears") or tld_min_registration_years(tld)),
        )
        quote = await svc.quote_registration_period_price(
            domain,
            max(period_years, min_years),
        )
        meta["price"] = float(quote["price"])
        meta["pricePerYear"] = float(quote["pricePerYear"])
        meta["period"] = int(quote["periodYears"])
        meta["minPeriodYears"] = int(quote.get("minPeriodYears") or min_years)
        meta["domainName"] = domain
        meta["tld"] = tld
        meta["priceSource"] = quote.get("priceSource")
        meta["commissionRate"] = quote.get("commissionRate")
        meta["isPremium"] = bool(quote.get("isPremium"))
        meta["registryTier"] = quote.get("registryTier") or (
            "premium" if quote.get("isPremium") else "standard"
        )
        if quote.get("providerUnitPriceInr") is not None:
            meta["providerUnitPriceInr"] = float(quote["providerUnitPriceInr"])
        if is_openprovider_managed_registration(meta):
            meta["isManagedAcquisition"] = True
        else:
            meta.pop("isManagedAcquisition", None)
        item.metadata_json = meta
        await self._repo.save(item)


    async def cleanup_stale_purchased_cart_items(self, user_id: uuid.UUID) -> int:
        """Purge stale cart items for products/domains already successfully purchased by user."""
        items = await self._repo.get_by_user(user_id)
        if not items:
            return 0

        stale_item_ids: list[uuid.UUID] = []

        from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
        from app.utils.registration_enums import RegistrationOrderStatus

        successful_statuses = (
            RegistrationOrderStatus.ACTIVE,
            RegistrationOrderStatus.REGISTRATION_PENDING,
            RegistrationOrderStatus.PAYMENT_COMPLETED,
        )
        stmt_reg = select(DomainRegistrationOrder).where(
            DomainRegistrationOrder.buyer_id == user_id,
            DomainRegistrationOrder.status.in_(successful_statuses),
        )
        res_reg = await self._session.execute(stmt_reg)
        reg_orders = res_reg.scalars().all()

        purchased_domains: set[str] = {
            f"{o.domain_name}{o.domain_extension}".lower().strip()
            for o in reg_orders
            if o.domain_name and o.domain_extension
        }
        purchased_reg_order_ids: set[str] = {str(o.id) for o in reg_orders}

        from app.entity.cobranding.domain_listing_entity import DomainListing
        from app.utils.marketplace_enums import DomainListingStatus, MarketplacePaymentStatus

        stmt_listings = select(DomainListing).where(
            (DomainListing.purchased_by_user_id == user_id)
            | (
                (DomainListing.listed_by_user_id != user_id)
                & (
                    (DomainListing.domain_status == DomainListingStatus.SOLD)
                    | (DomainListing.payment_status == MarketplacePaymentStatus.COMPLETED)
                )
            )
        )
        res_listings = await self._session.execute(stmt_listings)
        purchased_listings = res_listings.scalars().all()
        purchased_listing_ids: set[uuid.UUID] = {
            l.id for l in purchased_listings if l.purchased_by_user_id == user_id
        }

        for l in purchased_listings:
            fqdn = f"{l.domain_name}{l.domain_extension or ''}".lower().strip()
            if fqdn:
                purchased_domains.add(fqdn)

        from app.entity.cocreation.software_purchase_entity import SoftwarePurchase
        from app.utils.cocreation_enums import (
            SoftwarePurchaseCompletionStatus,
            SoftwarePaymentStatus,
        )

        stmt_sw = select(SoftwarePurchase).where(
            SoftwarePurchase.buyer_id == user_id,
            (
                (SoftwarePurchase.completion_status == SoftwarePurchaseCompletionStatus.CONFIRMED)
                | (SoftwarePurchase.payment_status == SoftwarePaymentStatus.COMPLETED)
            ),
        )
        res_sw = await self._session.execute(stmt_sw)
        purchased_software_ids: set[uuid.UUID] = {
            s.software_id for s in res_sw.scalars().all() if s.software_id
        }

        # Also detect completed technology-service subscriptions (provider-powered services
        # like AI Business Suite that live in technology_services_catalogue, not software_listings).
        from app.entity.technology_services.technology_subscription_entity import (
            TechnologySubscriptionEntity,
        )

        stmt_ts = select(TechnologySubscriptionEntity).where(
            TechnologySubscriptionEntity.user_id == str(user_id),
            TechnologySubscriptionEntity.status.in_(["ACTIVE", "PENDING"]),
            TechnologySubscriptionEntity.is_deleted.is_(False),
        )
        res_ts = await self._session.execute(stmt_ts)
        purchased_tech_sub_ids: set[str] = {
            str(s.provider_order_id)
            for s in res_ts.scalars().all()
            if s.provider_order_id
        }

        for item in items:
            meta = item.metadata_json or {}
            reg_order_id = str(
                meta.get("_checkout_registration_order_id")
                or meta.get("registration_order_id")
                or ""
            )
            if reg_order_id and reg_order_id in purchased_reg_order_ids:
                stale_item_ids.append(item.id)
                continue

            if item.product_type == CartProductType.DOMAIN_REGISTRATION:
                dn = str(meta.get("domainName") or meta.get("fullDomain") or "").lower().strip()
                if dn and dn in purchased_domains:
                    stale_item_ids.append(item.id)

            elif item.product_type == CartProductType.DOMAIN_LISTING:
                dn = str(meta.get("domainName") or meta.get("fullDomain") or "").lower().strip()
                if item.product_id in purchased_listing_ids or (dn and dn in purchased_domains):
                    stale_item_ids.append(item.id)

            elif item.product_type == CartProductType.TECHNOLOGY:
                if item.product_id in purchased_software_ids:
                    stale_item_ids.append(item.id)
                else:
                    meta = item.metadata_json or {}
                    provider_order = str(meta.get("providerOrderId") or "").strip()
                    if provider_order and provider_order in purchased_tech_sub_ids:
                        stale_item_ids.append(item.id)

        if stale_item_ids:
            deleted_count = await self._repo.delete_items_by_ids(stale_item_ids, user_id)
            await self._session.commit()
            logger.info(
                "[CART_STALE_CLEANUP] Deleted %s stale purchased cart item(s) for user=%s",
                deleted_count,
                user_id,
            )
            return deleted_count

        return 0

    async def get_cart(self, user_id: uuid.UUID) -> CartResponse:
        await self.cleanup_stale_purchased_cart_items(user_id)
        items = await self._repo.get_by_user(user_id)
        response_items: list[CartItemResponse] = []
        subtotal = 0.0

        for item in items:
            resp = await self._build_item_response(item)
            response_items.append(resp)
            if resp.available:
                subtotal += resp.line_total

        gst_breakdown = domain_price_breakdown(subtotal, years=1)
        gst = float(gst_breakdown["gstInr"])
        total = float(gst_breakdown["totalInr"])
        # Re-round for cart response contract.
        gst = round(gst, 2)
        total = round(total, 2)

        return CartResponse(
            items=response_items,
            item_count=len(response_items),
            subtotal=round(subtotal, 2),
            gst=gst,
            total=total,
            currency="INR",
        )

    async def get_item_count(self, user_id: uuid.UUID) -> int:
        await self.cleanup_stale_purchased_cart_items(user_id)
        return await self._repo.count_by_user(user_id)

    async def _validate_product_available(
        self,
        product_type: CartProductType,
        product_id: uuid.UUID,
        user_id: uuid.UUID,
        metadata: Optional[dict] = None,
    ) -> None:
        if product_type == CartProductType.DOMAIN_LISTING:
            listing = await self._get_domain_listing(product_id)
            if listing is None:
                raise AppException("Domain listing not found.", status_code=404)
            if listing.listed_by_user_id == user_id:
                raise AppException("You cannot add your own listing to cart.", status_code=400)
            if listing.domain_status == DomainListingStatus.UNDER_REVIEW:
                raise AppException(DOMAIN_UNAVAILABLE_MSG, status_code=409)
            if listing.domain_status not in (
                DomainListingStatus.AVAILABLE,
                DomainListingStatus.PENDING,
            ):
                raise AppException("This domain is not available.", status_code=400)

        elif product_type == CartProductType.TECHNOLOGY:
            software = await self._get_software(product_id)
            if software is not None:
                if software.listed_by_user_id == user_id:
                    raise AppException("You cannot add your own listing to cart.", status_code=400)
                if software.software_status != SoftwareStatus.AVAILABLE:
                    raise AppException("This technology is not available.", status_code=400)
                if software.purchase_type == SoftwarePurchaseType.AUCTION:
                    raise AppException("Auction items cannot be added to cart.", status_code=400)
            else:
                tech_service = await self._get_technology_service(product_id)
                if tech_service is None:
                    fallback = await self._get_technology_service_fallback(product_id)
                    if fallback is None:
                        raise AppException("Technology listing not found.", status_code=404)
                    if not fallback.get("is_available", True):
                        raise AppException("This technology is not available.", status_code=400)
                elif not tech_service.is_available:
                    raise AppException("This technology is not available.", status_code=400)

        elif product_type == CartProductType.VENTURE_DEAL:
            venture = await self._get_venture(product_id)
            if venture is None:
                raise AppException("Venture not found.", status_code=404)
            if venture.listed_by_user_id == user_id:
                raise AppException("You cannot add your own venture to cart.", status_code=400)
            if not self._is_venture_available(venture):
                raise AppException("This venture is not available.", status_code=400)

        elif product_type == CartProductType.DOMAIN_REGISTRATION:
            # A domain registration carries its price in the request metadata.
            # Reject a missing or non-positive price so the cart, taxes and
            # checkout total can never be silently built from ₹0.
            meta = metadata or {}
            try:
                price = float(meta.get("price"))
            except (TypeError, ValueError):
                price = 0.0
            if price <= 0:
                raise AppException(
                    "Registration price is unavailable for this domain.",
                    status_code=400,
                )
            # Ensure TLD minimum period metadata is present for cart/checkout.
            from app.integrations.openprovider.client import tld_min_registration_years

            domain = str(meta.get("domainName") or "").lower().strip()
            tld = str(
                meta.get("tld")
                or (domain.split(".", 1)[1] if "." in domain else "")
            ).lstrip(".")
            if tld:
                meta["tld"] = tld
                meta["minPeriodYears"] = max(
                    1,
                    int(meta.get("minPeriodYears") or tld_min_registration_years(tld)),
                )
                # Storefront add-to-cart is always the 1-year unit price.
                meta["period"] = max(1, int(meta.get("period") or 1))
                if metadata is not None:
                    metadata.update(meta)
            if meta.get("isPremium"):
                logger.info(
                    "analytics.premium_added_to_cart domain=%s price=%s",
                    domain,
                    price,
                )

    async def _build_item_response(self, item: CartItem) -> CartItemResponse:
        product_name: Optional[str] = None
        product_image: Optional[str] = None
        base_price: float = 0.0
        available: bool = True

        addon_keys = [k.strip() for k in (item.addon_services or "").split(",") if k.strip()]
        addon_amount = sum(float(ADDON_PRICES.get(k, 0)) for k in addon_keys)
        co_brother_fee = COBROTHER_FEE_INR if item.co_brother_opt_in else 0.0

        if item.product_type == CartProductType.DOMAIN_LISTING:
            listing = await self._get_domain_listing(item.product_id)
            if listing is None:
                available = False
                product_name = "Domain (unavailable)"
            else:
                product_name = f"{listing.domain_name}{listing.domain_extension or ''}"
                product_image = listing.image_url if hasattr(listing, "image_url") else None
                base_price = float(listing.asking_price or 0)
                if listing.domain_status not in (
                    DomainListingStatus.AVAILABLE,
                    DomainListingStatus.PENDING,
                ):
                    available = False
                if is_premium_marketplace_listing(listing):
                    meta = dict(item.metadata_json or {})
                    meta["isPremiumMarketplace"] = True
                    item.metadata_json = meta
                tax = domain_price_breakdown(base_price, years=1) if base_price > 0 else None
                if tax:
                    meta = dict(item.metadata_json or {})
                    meta["askingPrice"] = base_price
                    meta["gstInr"] = float(tax["gstInr"])
                    meta["gstRate"] = tax.get("gstRate")
                    meta["gstEnabled"] = bool(tax["gstEnabled"])
                    meta["buyerPayableInr"] = float(tax["totalInr"])
                    item.metadata_json = meta

        elif item.product_type == CartProductType.TECHNOLOGY:
            software = await self._get_software(item.product_id)
            if software is not None:
                product_name = software.name
                product_image = software.image_url
                base_price = float(software.price or 0)
                if item.selected_plan and software.pricing_plans:
                    from app.utils.cocreation_enums import TechnologyPricingPlanDuration

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
                if software.software_status != SoftwareStatus.AVAILABLE:
                    available = False
            else:
                tech_service = await self._get_technology_service(item.product_id)
                if tech_service is not None:
                    product_name = tech_service.name
                    product_image = None
                    if not tech_service.is_available:
                        available = False
                    base_price = await self._tech_service_price_inr(
                        tech_service, item.selected_plan, item.metadata_json
                    )
                else:
                    fallback = await self._get_technology_service_fallback(item.product_id)
                    if fallback is not None:
                        product_name = fallback["name"]
                        product_image = None
                        if not fallback.get("is_available", True):
                            available = False
                        base_price = await self._tech_service_price_inr_dict(
                            fallback, item.selected_plan, item.metadata_json
                        )
                    else:
                        available = False
                        product_name = "Technology (unavailable)"

        elif item.product_type == CartProductType.VENTURE_DEAL:
            venture = await self._get_venture(item.product_id)
            if venture is None:
                available = False
                product_name = "Venture (unavailable)"
            else:
                product_name = venture.name if hasattr(venture, "name") else "Venture"
                product_image = venture.image_url if hasattr(venture, "image_url") else None
                brand = venture.brand_details if hasattr(venture, "brand_details") else None
                if brand and hasattr(brand, "deal_value"):
                    base_price = float(brand.deal_value or 0)
                if not self._is_venture_available(venture):
                    available = False

        elif item.product_type == CartProductType.DOMAIN_REGISTRATION:
            meta = dict(item.metadata_json or {})
            product_name = meta.get("domainName", "Domain Registration")
            base_price = float(meta.get("price", 0))
            if is_openprovider_managed_registration(meta):
                meta["isManagedAcquisition"] = True
                item.metadata_json = meta

        line_total = round(base_price + addon_amount + co_brother_fee, 2)

        # Expose public metadata for domain registrations (period, pricePerYear)
        # and premium marketplace acquisition flags.
        # Strip checkout-only keys that must never reach the client.
        public_meta: Optional[dict[str, Any]] = None
        if item.product_type == CartProductType.DOMAIN_REGISTRATION and item.metadata_json:
            public_meta = {
                k: v
                for k, v in item.metadata_json.items()
                if not str(k).startswith("_checkout_")
            }
        elif item.product_type == CartProductType.DOMAIN_LISTING and item.metadata_json:
            public_meta = {
                k: v
                for k, v in item.metadata_json.items()
                if k in (
                    "isPremiumMarketplace",
                    "askingPrice",
                    "gstInr",
                    "gstRate",
                    "gstEnabled",
                    "buyerPayableInr",
                )
            } or None

        return CartItemResponse(
            id=item.id,
            productType=item.product_type,
            productId=item.product_id,
            selectedPlan=item.selected_plan,
            addonServices=addon_keys if addon_keys else None,
            coBrotherOptIn=item.co_brother_opt_in,
            productName=product_name,
            productImage=product_image,
            basePrice=base_price,
            addonAmount=addon_amount,
            coBrotherFee=co_brother_fee,
            lineTotal=line_total,
            available=available,
            metadata=public_meta,
        )

    async def _get_domain_listing(self, listing_id: uuid.UUID) -> Optional[DomainListing]:
        stmt = select(DomainListing).where(
            DomainListing.id == listing_id,
            DomainListing.is_deleted.is_(False),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_software(self, software_id: uuid.UUID) -> Optional[Software]:
        from sqlalchemy.orm import selectinload
        from app.entity.cocreation.technology_pricing_plan_entity import TechnologyPricingPlan

        stmt = (
            select(Software)
            .where(Software.id == software_id, Software.is_deleted.is_(False))
            .options(selectinload(Software.pricing_plans))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_technology_service(self, service_id: uuid.UUID) -> Optional[TechnologyServiceEntity]:
        stmt = (
            select(TechnologyServiceEntity)
            .where(
                TechnologyServiceEntity.id == service_id,
                TechnologyServiceEntity.is_deleted.is_(False),
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_technology_service_fallback(self, service_id: uuid.UUID) -> Optional[dict[str, Any]]:
        """Resolve a deterministic-uuid fallback catalogue entry when the DB lookup misses.

        The technology-services catalogue fallback exposes uuid5 IDs (see
        ``_fallback_service_id``). When the DB is unavailable those IDs are still
        valid UUIDs, so the cart must recognise them and serve the seeded plan data.
        """
        from app.controller.technology.technology_services_controller import (
            DEFAULT_SERVICES_SEED,
            _fallback_service_id,
        )
        for item in DEFAULT_SERVICES_SEED:
            if str(_fallback_service_id(item["slug"])) == str(service_id):
                return {
                    "slug": item["slug"],
                    "name": item["name"],
                    "is_available": True,
                    "plans_json": json.dumps(item["plans"]),
                    "price_override_monthly": None,
                    "price_override_annually": None,
                }
        return None

    @staticmethod
    def _tech_service_plan_price_inr(
        plans_json: Optional[str],
        selected_plan: Optional[str],
        metadata: Optional[dict],
        override_monthly: Optional[float] = None,
        override_annually: Optional[float] = None,
    ) -> float:
        """Resolve a technology-service plan price in INR (plans are stored in USD)."""
        from app.service.currency.exchange_rate_service import convert_foreign_to_inr

        plans: list[dict] = []
        if plans_json:
            try:
                plans = json.loads(plans_json)
            except (ValueError, TypeError):
                plans = []
        if not plans:
            return 0.0

        plan = None
        if selected_plan:
            plan = next((p for p in plans if p.get("code") == selected_plan), None)
        if plan is None:
            plan = plans[0]

        billing_cycle = "annual" if str(metadata.get("billingCycle", "")).lower().startswith("ann") else "monthly"
        price_key = "price_annually" if billing_cycle == "annual" else "price_monthly"
        usd_price = float(plan.get(price_key) or plan.get("price_monthly", 0))

        if billing_cycle == "annual" and override_annually is not None:
            usd_price = float(override_annually)
        elif billing_cycle == "monthly" and override_monthly is not None:
            usd_price = float(override_monthly)

        if usd_price <= 0:
            return 0.0

        try:
            conversion = convert_foreign_to_inr(usd_price, "USD")
            return float(conversion["amountInr"])
        except Exception as exc:
            logger.warning("Technology service USD→INR conversion failed: %s", exc)
            return 0.0

    async def _tech_service_price_inr(
        self,
        service: TechnologyServiceEntity,
        selected_plan: Optional[str],
        metadata: Optional[dict],
    ) -> float:
        return self._tech_service_plan_price_inr(
            service.plans_json,
            selected_plan,
            metadata,
            override_monthly=service.price_override_monthly,
            override_annually=service.price_override_annually,
        )

    async def _tech_service_price_inr_dict(
        self,
        fallback: dict,
        selected_plan: Optional[str],
        metadata: Optional[dict],
    ) -> float:
        return self._tech_service_plan_price_inr(
            fallback.get("plans_json"),
            selected_plan,
            metadata,
            override_monthly=fallback.get("price_override_monthly"),
            override_annually=fallback.get("price_override_annually"),
        )


    async def _get_venture(self, venture_id: uuid.UUID) -> Optional[Venture]:
        stmt = select(Venture).where(
            Venture.id == venture_id,
            Venture.is_deleted.is_(False),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def _is_venture_available(venture: Venture) -> bool:
        if venture.taken_down:
            return False
        if venture.purchased_by_user_id is not None:
            return False
        return venture.venture_listing_status == VentureListingStatus.ACTIVE
