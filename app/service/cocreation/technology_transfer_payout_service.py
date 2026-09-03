"""Technology marketplace seller payout approval and release."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.payout.seller_payout_entity import SellerPayout
from app.entity.user.app_user import AppUser
from app.repository.software_purchase_repository import SoftwarePurchaseRepository
from app.repository.seller_payout_profile_repository import SellerPayoutProfileRepository
from app.service.payout.seller_payout_profile_service import SellerPayoutProfileService
from app.utils.transfer_enums import SellerPayoutStatus


class TechnologyTransferPayoutService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SoftwarePurchaseRepository(session)
        self._profiles = SellerPayoutProfileRepository(session)

    async def _require_complete_profile(self, seller_id: uuid.UUID):
        profile = await self._profiles.get_by_user_id(seller_id)
        if not SellerPayoutProfileService.is_complete(profile):
            raise AppException(
                "Cannot approve payout. Seller payout profile is incomplete.",
                status_code=400,
            )
        return profile

    async def approve_payout(self, tx_id: uuid.UUID, *, admin: AppUser) -> dict:
        tx = await self._repo.get_by_id_for_update(tx_id)
        if tx is None:
            raise AppException("Software purchase transaction not found.", status_code=404)
        if tx.seller_paid_at:
            raise AppException("Payout is already completed.", status_code=400)
            
        seller_id = tx.software.listed_by_user_id
        if seller_id is None:
            raise AppException("Software listing has no seller.", status_code=400)

        profile = await self._require_complete_profile(seller_id)
        now = datetime.now(timezone.utc)
        
        tx.payout_approved_by_user_id = admin.id
        tx.payout_approved_at = now
        await self._repo.save(tx)
        await self._session.commit()
        
        return {"success": True, "payoutApprovedAt": now.isoformat()}

    async def release_payout(
        self,
        tx_id: uuid.UUID,
        *,
        admin: AppUser,
        payout_method_used: str = "MANUAL",
        transaction_reference_number: str | None = None,
        notes: str | None = None,
    ) -> dict:
        tx = await self._repo.get_by_id_for_update(tx_id)
        if tx is None:
            raise AppException("Software purchase transaction not found.", status_code=404)
        if tx.payout_approved_at is None:
            raise AppException("Payout must be approved before release.", status_code=400)
        if tx.seller_paid_at:
            raise AppException("Payout is already completed.", status_code=400)
            
        seller_id = tx.software.listed_by_user_id
        if seller_id is None:
            raise AppException("Software listing has no seller.", status_code=400)

        reference_number = (transaction_reference_number or "").strip() or f"manual-{tx.id}"
        profile = await self._require_complete_profile(seller_id)
        now = datetime.now(timezone.utc)
        
        tx.seller_paid_at = now
        payout = SellerPayout(
            software_purchase_id=tx.id,
            payout_profile_id=profile.id,
            seller_id=seller_id,
            amount_inr=tx.seller_payout_inr,
            status=SellerPayoutStatus.SENT,
            method_used=payout_method_used,
            reference_number=reference_number,
            notes=(notes or "").strip() or None,
            released_by_user_id=admin.id,
            released_at=now,
            sent_at=now,
        )
        self._session.add(payout)
        await self._repo.save(tx)
        
        # NOTE: DomainTransferEventService logs event here for Domain. Since it's software, we skip for now unless requested.
        await self._session.commit()
        return {"success": True, "payoutReleasedAt": now.isoformat()}
