"""Admin Blacklist Users — unpaid auction winners (platform_settings backed)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user, require_role
from app.entity.user.app_user import AppUser
from app.service.auction.winner_payment_lifecycle import WinnerPaymentLifecycleAsync

router = APIRouter(
    prefix="/api/v1/admin/bidding-blocks",
    tags=["Admin Bidding Blocks"],
)


@router.get("")
async def list_bidding_blocks(
    db: AsyncSession = Depends(get_async_db),
    _admin: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN"])),
):
    life = WinnerPaymentLifecycleAsync(db)
    rows = await life.list_blocked_users()
    return {"success": True, "count": len(rows), "data": rows}


@router.post("/{user_id}/unblacklist")
async def unblacklist_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    admin: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN"])),
):
    life = WinnerPaymentLifecycleAsync(db)
    ok = await life.unblock_user(user_id, by_admin_id=admin.id)
    await db.commit()
    return {"success": ok, "userId": str(user_id)}
