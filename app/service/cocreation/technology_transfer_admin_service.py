"""Admin service for mapping software purchases to marketplace transfer DTOs."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.cocreation.software_purchase_entity import SoftwarePurchase
from app.model.marketplace.transfer_mapper import _user_summary
from app.repository.seller_payout_profile_repository import SellerPayoutProfileRepository
from app.service.payout.seller_payout_profile_service import SellerPayoutProfileService
from app.utils.transfer_enums import MarketplaceEscrowStatus, MarketplaceTransferStatus


class TechnologyTransferAdminService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._profiles = SellerPayoutProfileRepository(session)

    async def serialize(
        self,
        purchase: SoftwarePurchase,
        include_payout_profile: bool = False,
    ) -> dict[str, Any]:
        
        escrow_status = MarketplaceEscrowStatus.HELD
        if purchase.seller_paid_at:
            escrow_status = MarketplaceEscrowStatus.RELEASED
            
        transfer_status = MarketplaceTransferStatus.COMPLETED
        if not purchase.seller_paid_at:
            transfer_status = MarketplaceTransferStatus.PAYOUT_PENDING
        if purchase.payout_approved_at and not purchase.seller_paid_at:
            transfer_status = MarketplaceTransferStatus.PAYOUT_APPROVED

        # For mapping domain listing ID in the UI to something recognizable
        domain_listing_id = str(purchase.software_id) if purchase.software_id else ""
        
        # We pass purchase.id as id so the UI endpoints hit /api/v1/admin/domain-transfers/{purchase_id}/...
        payload = {
            "id": str(purchase.id),
            "domainListingId": domain_listing_id,
            "domainFqdn": purchase.software.name if purchase.software else "Technology",
            "buyer": _user_summary(purchase.buyer),
            "seller": _user_summary(purchase.software.listed_by) if purchase.software else None,
            "grossAmountInr": purchase.gross_amount_inr,
            "platformFeeInr": purchase.platform_fee_inr,
            "sellerPayoutInr": purchase.seller_payout_inr,
            "razorpayOrderId": purchase.razorpay_order_id,
            "razorpayPaymentId": purchase.razorpay_payment_id,
            "escrowStatus": escrow_status.value,
            "transferStatus": transfer_status.value,
            "transferMethod": None,
            "assistanceRequestedAt": None,
            "sellerRegistrarName": None,
            "buyerTargetRegistrar": None,
            "sellerDeadlineAt": None,
            "buyerDeadlineAt": None,
            "authCodeSubmittedAt": None,
            "authCodeViewedAt": None,
            "transferStartedAt": purchase.created_at.isoformat() if purchase.created_at else None,
            "transferConfirmedAt": purchase.sold_at.isoformat() if purchase.sold_at else None,
            "transferVerifiedBy": None,
            "whoisSupportsTransfer": None,
            "whoisRegistrarSnapshot": None,
            "disputeStatus": "NONE",
            "cobrotherRequestId": None,
            "adminReviewRequiredAt": None,
            "adminReviewReason": None,
            "sellerPaidAt": purchase.seller_paid_at.isoformat() if purchase.seller_paid_at else None,
            "payoutApprovedAt": purchase.payout_approved_at.isoformat() if purchase.payout_approved_at else None,
            "refundCompletedAt": None,
            "hasAuthCode": False,
            "authCode": None,
            "createdAt": purchase.created_at.isoformat() if purchase.created_at else None,
            "updatedAt": purchase.updated_at.isoformat() if purchase.updated_at else None,
            "isTechnology": True, # A flag to identify it in the UI/backend
        }

        if include_payout_profile and purchase.software and purchase.software.listed_by_user_id:
            seller_id = purchase.software.listed_by_user_id
            profile = await self._profiles.get_by_user_id(seller_id)
            profile_complete = SellerPayoutProfileService.is_complete(profile)
            payout_profile_payload = (
                SellerPayoutProfileService(self._session)._serialize(profile) if profile else None
            )
            if profile and payout_profile_payload:
                full_account_number = (profile.account_number or "").strip()
                masked_account_number = (
                    SellerPayoutProfileService._masked_account_number(
                        full_account_number,
                        profile.account_number_last4,
                    )
                    if full_account_number
                    else None
                )
                payout_profile_payload.update(
                    {
                        "upiId": None,
                        "accountNumber": full_account_number or None,
                        "account_number": full_account_number or None,
                        "accountNumberLast4": profile.account_number_last4,
                        "account_number_last4": profile.account_number_last4,
                        "bankAccountNumber": full_account_number or None,
                        "maskedAccountNumber": masked_account_number,
                        "masked_account_number": masked_account_number,
                        "fullAccountNumber": full_account_number or None,
                        "full_account_number": full_account_number or None,
                    }
                )
            
            payload["sellerPayoutProfile"] = (
                {
                    **payout_profile_payload,
                    "kycStatus": profile.kyc_status.value,
                    "beneficiaryValidatedAt": (
                        profile.beneficiary_validated_at.isoformat()
                        if profile.beneficiary_validated_at
                        else None
                    ),
                }
                if profile
                else None
            )
            payload["sellerPayoutProfileMissing"] = profile is None
            payload["sellerPayoutProfileReady"] = profile_complete
            
            payload["lastPayoutReminderSentAt"] = (
                purchase.payout_reminder_sent_at.isoformat() if purchase.payout_reminder_sent_at else None
            )
            payload["payoutReminderCount"] = int(purchase.payout_reminder_count or 0)
            
            # Fetch payout history
            from sqlalchemy import select
            from app.entity.payout.seller_payout_entity import SellerPayout
            from app.entity.user.app_user import AppUser
            
            payout_rows = (
                await self._session.execute(
                    select(SellerPayout)
                    .where(SellerPayout.software_purchase_id == purchase.id)
                    .order_by(SellerPayout.released_at.desc().nullslast(), SellerPayout.created_at.desc())
                )
            ).scalars().all()
            
            released_by_ids = [row.released_by_user_id for row in payout_rows if row.released_by_user_id]
            released_by: dict[uuid.UUID, AppUser] = {}
            if released_by_ids:
                users = (
                    await self._session.execute(
                        select(AppUser).where(AppUser.id.in_(released_by_ids))
                    )
                ).scalars().all()
                released_by = {user.id: user for user in users}
                
            payload["payoutHistory"] = [
                {
                    "id": str(row.id),
                    "releaseDate": row.released_at.isoformat() if row.released_at else None,
                    "method": row.method_used,
                    "referenceNumber": row.reference_number,
                    "releasedBy": self._format_user_name(released_by.get(row.released_by_user_id)),
                    "releasedByUserId": (
                        str(row.released_by_user_id) if row.released_by_user_id else None
                    ),
                    "status": row.status.value,
                    "notes": row.notes,
                }
                for row in payout_rows
            ]
        return payload

    @staticmethod
    def _format_user_name(user: AppUser | None) -> str | None:
        if user is None:
            return None
        name = f"{user.firstname or ''} {user.lastname or ''}".strip()
        return name or user.email
