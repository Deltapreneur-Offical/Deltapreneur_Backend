"""Seller payout profile endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.entity.user.app_user import AppUser
from app.service.payout.seller_payout_profile_service import SellerPayoutProfileService

router = APIRouter(prefix="/api/v1/payout-profile", tags=["Payout Profile"])


@router.get("/me")
async def get_my_payout_profile(
    user: AppUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    profile = await SellerPayoutProfileService(db).get_my_profile(user)
    return {"profile": profile}


@router.post("/me")
async def upsert_my_payout_profile(
    request: Request,
    payout_method: str = Form(...),
    account_holder_name: str | None = Form(None),
    bank_name: str | None = Form(None),
    account_number: str | None = Form(None),
    bank_account_number: str | None = Form(None),
    confirm_account_number: str | None = Form(None),
    confirm_bank_account_number: str | None = Form(None),
    bank_ifsc: str | None = Form(None),
    upi_id: str | None = Form(None),
    kyc_file: UploadFile | None = File(None),
    user: AppUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    profile = await SellerPayoutProfileService(db).upsert_profile(
        user,
        payout_method=payout_method,
        account_holder_name=account_holder_name,
        bank_name=bank_name,
        bank_account_number=account_number or bank_account_number,
        confirm_bank_account_number=confirm_account_number or confirm_bank_account_number,
        bank_ifsc=bank_ifsc,
        upi_id=upi_id,
        kyc_file=kyc_file,
        ip_address=request.client.host if request.client else None,
    )
    return {"profile": profile}
