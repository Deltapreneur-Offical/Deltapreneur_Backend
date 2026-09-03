"""Admin endpoints for domain registration orders."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user, require_role
from app.entity.user.app_user import AppUser
from app.service.domain.domain_registration_ops_service import DomainRegistrationOpsService
from app.service.domain import domain_commission_config as commission

router = APIRouter(
    prefix="/api/v1/admin/domain-registrations",
    tags=["Admin Domain Registrations"],
)


async def get_ops_service(
    db: AsyncSession = Depends(get_async_db),
) -> DomainRegistrationOpsService:
    return DomainRegistrationOpsService(db)


@router.get("/")
async def list_registration_orders(
    status: str | None = Query(None),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    service: DomainRegistrationOpsService = Depends(get_ops_service),
) -> list:
    return await service.admin_list_orders(status=status)


@router.post("/{order_id}/retry")
async def admin_retry_provision(
    order_id: uuid.UUID,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    service: DomainRegistrationOpsService = Depends(get_ops_service),
) -> dict:
    return await service.admin_retry(order_id)


@router.post("/{order_id}/refund")
async def admin_refund_order(
    order_id: uuid.UUID,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    service: DomainRegistrationOpsService = Depends(get_ops_service),
) -> dict:
    return await service.admin_refund(order_id)


@router.patch("/{order_id}/tax-invoice")
async def admin_set_tax_invoice(
    order_id: uuid.UUID,
    body: dict,
    _admin: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN"])),
    service: DomainRegistrationOpsService = Depends(get_ops_service),
) -> dict:
    """Admin override of tax invoice number shown on the buyer's Purchases invoice."""
    raw = body.get("taxInvoiceNumber") or body.get("tax_invoice_number") or body.get("invoiceNumber")
    return await service.admin_set_tax_invoice(order_id, str(raw or ""))


# ── Commission / Markup config ────────────────────────────────────────────────

@router.get("/commission")
async def get_commission_config(
    _admin: AppUser = Depends(require_role(["ADMIN"])),
) -> dict:
    """Return current commission/markup rates for all domain services."""
    return {"success": True, "data": commission.load()}


@router.put("/commission")
async def update_commission_config(
    body: dict,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
) -> dict:
    """Update commission/markup rates. Body should match the commission config schema."""
    try:
        # Validate structure — only allow known service keys
        allowed = set(commission.CommissionService.ALL)
        filtered = {k: v for k, v in body.items() if k in allowed}
        # Load existing and merge
        current = commission.load()
        for key, val in filtered.items():
            if isinstance(val, dict):
                current[key] = {**current.get(key, {}), **val}
            else:
                current[key] = val
        commission.save(current)
        # Invalidate cached storefront search responses so the new commission is
        # reflected immediately instead of after the cache TTL.
        from app.service.domain.domain_registration_service import clear_tld_search_cache
        clear_tld_search_cache()
        return {"success": True, "message": "Commission config updated.", "data": current}
    except Exception as exc:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(exc)},
        )

