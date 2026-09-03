"""Admin addon orders (domain purchases with add-ons and related records)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import nulls_last, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

from app.entity.cobranding.domain_listing_entity import DomainListing
from app.entity.cocreation.software_entity import Software
from app.entity.cocreation.software_purchase_entity import SoftwarePurchase
from app.entity.cobrother.cobrother_request_entity import CoBrotherRequest
from app.entity.user.app_user import AppUser
from app.utils.cocreation_enums import SoftwarePaymentStatus
from app.utils.marketplace_enums import CoBrotherRequestStatus, CoBrotherRequestType

from app.utils.addon_services import ADDON_PRICES, format_phone_display

_ADDON_PRICES = ADDON_PRICES


def _addon_total_from_keys(keys_csv: str) -> float:
    if not keys_csv:
        return 0.0
    total = 0.0
    for key in keys_csv.split(","):
        k = key.strip()
        if k:
            total += float(_ADDON_PRICES.get(k, 0))
    return total


class AddonAdminService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_addon_orders(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []

        domain_rows: list[DomainListing] = []
        try:
            domain_stmt = (
                select(DomainListing)
                .where(
                    DomainListing.purchase_addon_services.isnot(None),
                    DomainListing.purchase_addon_services != "",
                )
                .order_by(DomainListing.updated_at.desc())
            )
            domain_rows = (await self._session.execute(domain_stmt)).scalars().all()
        except ProgrammingError as exc:
            await self._session.rollback()
            logger.warning(
                "addon domain orders skipped (run alembic upgrade head): %s",
                exc.orig if hasattr(exc, "orig") else exc,
            )

        for listing in domain_rows:
            buyer = None
            if listing.purchased_by_user_id:
                buyer = (
                    await self._session.execute(
                        select(AppUser).where(AppUser.id == listing.purchased_by_user_id)
                    )
                ).scalar_one_or_none()
            buyer_name = listing.purchase_buyer_name
            if not buyer_name and buyer:
                buyer_name = " ".join(
                    p for p in (buyer.firstname, buyer.lastname) if p
                ).strip()
            addon_total = _addon_total_from_keys(listing.purchase_addon_services or "")
            domain_price = float(listing.asking_price or 0)
            payment = (
                listing.payment_status.value
                if listing.payment_status is not None
                else "CREATED"
            )
            out.append(
                {
                    "id": str(listing.id),
                    "buyerName": buyer_name or "—",
                    "buyerEmail": listing.purchase_buyer_email
                    or (buyer.email if buyer else ""),
                    "buyerPhone": format_phone_display(
                        listing.purchase_buyer_phone
                        or (buyer.phone_number if buyer else "")
                    ),
                    "purchaseType": "DOMAIN",
                    "purchaseId": listing.id,
                    "selectedServices": listing.purchase_addon_services,
                    "totalAmount": domain_price + addon_total,
                    "paymentStatus": payment,
                    "createdAt": listing.created_at.isoformat()
                    if listing.created_at
                    else None,
                }
            )

        purchases: list[SoftwarePurchase] = []
        try:
            stmt = (
                select(SoftwarePurchase)
                .where(SoftwarePurchase.payment_status == SoftwarePaymentStatus.COMPLETED)
                .options(
                    selectinload(SoftwarePurchase.buyer),
                    selectinload(SoftwarePurchase.software).selectinload(Software.listed_by),
                )
                .order_by(
                    nulls_last(SoftwarePurchase.sold_at.desc()),
                    SoftwarePurchase.created_at.desc(),
                )
            )
            purchases = (await self._session.execute(stmt)).scalars().all()
        except ProgrammingError as exc:
            await self._session.rollback()
            logger.warning(
                "addon software orders skipped (run alembic upgrade head): %s",
                exc.orig if hasattr(exc, "orig") else exc,
            )

        for p in purchases:
            sw = p.software
            if sw is None:
                continue
            buyer = p.buyer
            buyer_phone = format_phone_display(
                p.buyer_phone or (buyer.phone_number if buyer else "")
            )

            addon_keys = (p.purchase_addon_services or "").strip()
            selected = addon_keys
            if p.co_brother_opt_in:
                parts = [k.strip() for k in addon_keys.split(",") if k.strip()]
                if "COBROTHER_HELPER" not in parts:
                    parts.insert(0, "COBROTHER_HELPER")
                selected = ",".join(parts)

            if not selected and not p.co_brother_opt_in:
                continue

            req_stmt = (
                select(CoBrotherRequest)
                .where(
                    CoBrotherRequest.request_type == CoBrotherRequestType.COCREATION,
                    CoBrotherRequest.entity_id.in_([p.id, sw.id]),
                    CoBrotherRequest.status.not_in(
                        [CoBrotherRequestStatus.CANCELLED, CoBrotherRequestStatus.REJECTED]
                    ),
                )
                .order_by(CoBrotherRequest.created_at.desc())
                .limit(1)
            )
            active_req = (await self._session.execute(req_stmt)).scalar_one_or_none()

            out.append(
                {
                    "id": f"sw-{p.id}",
                    "purchaseId": p.id,
                    "buyerName": p.buyer_full_name
                    or (
                        " ".join(
                            x for x in (buyer.firstname, buyer.lastname) if x
                        ).strip()
                        if buyer
                        else "—"
                    ),
                    "buyerEmail": p.buyer_email or (buyer.email if buyer else ""),
                    "buyerPhone": buyer_phone,
                    "purchaseType": "TECHNOLOGY",
                    "selectedServices": selected,
                    "totalAmount": float(sw.price or 0)
                    + (1000.0 if p.co_brother_help_paid else 0.0),
                    "paymentStatus": p.payment_status.value,
                    "createdAt": p.created_at.isoformat() if p.created_at else None,
                    "coBrotherOptIn": p.co_brother_opt_in,
                    "coBrotherHelpPaid": p.co_brother_help_paid,
                    "activeCoBrotherRequest": (
                        {"id": str(active_req.id), "status": active_req.status.value}
                        if active_req
                        else None
                    ),
                }
            )

        out.sort(key=lambda row: row.get("createdAt") or "", reverse=True)
        return out
