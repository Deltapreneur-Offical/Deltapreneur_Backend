"""Admin APIs for technology marketplace transfers and payouts."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import require_role
from app.core.exceptions import AppException
from app.entity.user.app_user import AppUser
from app.model.marketplace.transfer_request import ReleasePayoutRequest
from app.repository.software_purchase_repository import SoftwarePurchaseRepository
from app.service.cocreation.technology_transfer_admin_service import TechnologyTransferAdminService
from app.service.cocreation.technology_transfer_payout_service import TechnologyTransferPayoutService

router = APIRouter(prefix="/api/v1/admin/technology-transfers", tags=["Admin Technology Transfers"])


@router.get("/")
async def list_transfers(
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    tech_repo = SoftwarePurchaseRepository(db)
    tech_service = TechnologyTransferAdminService(db)
    tech_rows = await tech_repo.list_for_admin(limit=limit, offset=offset)
    
    items = []
    for tx in tech_rows:
        serialized = await tech_service.serialize(tx, include_payout_profile=True)
        items.append(serialized)
        
    items.sort(key=lambda x: x.get("createdAt") or "", reverse=True)
    return {"items": items}


@router.get("/{transaction_id}")
async def get_transfer_admin_detail(
    transaction_id: uuid.UUID,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    tx = await SoftwarePurchaseRepository(db).get_by_id(transaction_id)
    if not tx:
        raise AppException("Transfer transaction not found.", status_code=404)
    payload = await TechnologyTransferAdminService(db).serialize(tx, include_payout_profile=True)
    payload["timeline"] = []
    return payload


@router.post("/{transaction_id}/approve-payout")
async def approve_payout(
    transaction_id: uuid.UUID,
    admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    return await TechnologyTransferPayoutService(db).approve_payout(transaction_id, admin=admin)


@router.post("/{transaction_id}/release-payout")
async def release_payout(
    transaction_id: uuid.UUID,
    body: ReleasePayoutRequest,
    admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    return await TechnologyTransferPayoutService(db).release_payout(
        transaction_id,
        admin=admin,
        payout_method_used=body.payout_method_used,
        transaction_reference_number=body.transaction_reference_number,
        notes=body.notes,
    )
