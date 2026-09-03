"""Seller payout approval and release."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.payout.seller_payout_entity import SellerPayout
from app.entity.user.app_user import AppUser
from app.repository.domain_marketplace_transaction_repository import (
    DomainMarketplaceTransactionRepository,
)
from app.repository.seller_payout_profile_repository import SellerPayoutProfileRepository
from app.service.domain.domain_transfer_event_service import DomainTransferEventService
from app.service.domain.domain_transfer_notification_service import (
    DomainTransferNotificationService,
)
from app.service.payout.seller_payout_profile_service import SellerPayoutProfileService
from app.utils.transfer_enums import (
    MarketplaceEscrowStatus,
    MarketplaceTransferStatus,
    SellerPayoutStatus,
    TransferEventType,
)


class DomainTransferPayoutService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DomainMarketplaceTransactionRepository(session)
        self._profiles = SellerPayoutProfileRepository(session)
        self._events = DomainTransferEventService(session)
        self._notify = DomainTransferNotificationService(session)

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
            raise AppException("Transfer transaction not found.", status_code=404)
        if tx.transfer_status in (
            MarketplaceTransferStatus.REFUNDED,
            MarketplaceTransferStatus.CANCELLED,
        ):
            raise AppException("Transaction has been refunded/cancelled; payout is not eligible.", status_code=409)
        if tx.escrow_status == MarketplaceEscrowStatus.REFUNDED:
            raise AppException("Escrow has been refunded; payout is not eligible.", status_code=409)
        if tx.transfer_status not in (
            MarketplaceTransferStatus.TRANSFER_COMPLETED,
            MarketplaceTransferStatus.PAYOUT_PENDING,
        ):
            raise AppException("Transfer must be completed before payout approval.", status_code=400)
        if tx.escrow_status != MarketplaceEscrowStatus.HELD:
            raise AppException("Escrow is not held; cannot approve payout.", status_code=409)
        profile = await self._require_complete_profile(tx.seller_id)
        now = datetime.now(timezone.utc)
        tx.payout_profile_id = profile.id
        tx.payout_approved_by_user_id = admin.id
        tx.payout_approved_at = now
        tx.transfer_status = MarketplaceTransferStatus.PAYOUT_APPROVED
        # Capture historical payout snapshot on the transaction itself.
        tx.payout_snapshot_method = profile.payout_method.value if profile.payout_method else None
        tx.payout_snapshot_account_holder = profile.account_holder_name
        tx.payout_snapshot_bank_name = profile.bank_name
        tx.payout_snapshot_ifsc = profile.bank_ifsc
        tx.payout_snapshot_account_number = (profile.account_number or "").strip() or None
        tx.payout_snapshot_account_last4 = profile.account_number_last4
        # Decrypt UPI for snapshot
        try:
            from app.service.security.auth_code_encryption_service import decrypt_secret
            tx.payout_snapshot_upi_id = decrypt_secret(profile.upi_id_encrypted) if profile.upi_id_encrypted else None
        except Exception:
            tx.payout_snapshot_upi_id = None
        tx.payout_snapshot_captured_at = now
        tx.payout_snapshot_source = "PAYOUT_APPROVAL"
        await self._repo.save(tx)
        # Audit event snapshot
        snapshot = {
            "approved": True,
            "payoutProfileId": str(profile.id),
            "payoutMethod": profile.payout_method.value if profile.payout_method else None,
            "accountHolderName": profile.account_holder_name,
            "bankName": profile.bank_name,
            "bankIfsc": profile.bank_ifsc,
            "accountNumberLast4": profile.account_number_last4,
            "sellerPayoutInr": tx.seller_payout_inr,
            "sellerId": str(tx.seller_id),
        }
        await self._events.log(
            tx.id,
            TransferEventType.PAYOUT_APPROVED,
            actor_user_id=admin.id,
            actor_role="ADMIN",
            payload=snapshot,
        )
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
            raise AppException("Transfer transaction not found.", status_code=404)
        if tx.transfer_status in (
            MarketplaceTransferStatus.REFUNDED,
            MarketplaceTransferStatus.CANCELLED,
        ):
            raise AppException("Transaction has been refunded/cancelled; payout cannot be released.", status_code=409)
        if tx.escrow_status == MarketplaceEscrowStatus.REFUNDED:
            raise AppException("Escrow has been refunded; payout cannot be released.", status_code=409)
        if tx.transfer_status != MarketplaceTransferStatus.PAYOUT_APPROVED:
            raise AppException("Payout must be approved before release.", status_code=400)
        if tx.payout_approved_at is None:
            raise AppException("Payout must be approved before release.", status_code=400)
        if tx.escrow_status != MarketplaceEscrowStatus.HELD:
            raise AppException("Escrow is not held.", status_code=400)
        reference_number = (transaction_reference_number or "").strip() or f"manual-{tx.id}"
        profile = await self._require_complete_profile(tx.seller_id)
        now = datetime.now(timezone.utc)
        tx.payout_profile_id = profile.id
        tx.escrow_status = MarketplaceEscrowStatus.RELEASED
        tx.transfer_status = MarketplaceTransferStatus.COMPLETED
        tx.seller_paid_at = now
        payout = SellerPayout(
            transaction_id=tx.id,
            payout_profile_id=profile.id,
            seller_id=tx.seller_id,
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
        await self._events.log(
            tx.id,
            TransferEventType.PAYOUT_RELEASED,
            actor_user_id=admin.id,
            actor_role="ADMIN",
            payload={
                "sellerPayoutInr": tx.seller_payout_inr,
                "methodUsed": payout_method_used,
                "referenceNumber": reference_number,
            },
        )
        await self._notify.on_payout_released(tx)
        await self._session.commit()
        return {
            "success": True,
            "sellerPaidAt": now.isoformat(),
            "status": tx.transfer_status.value,
        }
