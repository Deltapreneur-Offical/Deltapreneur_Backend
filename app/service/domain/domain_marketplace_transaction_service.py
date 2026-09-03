"""Create and fetch domain marketplace transfer transactions."""

from __future__ import annotations

import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.entity.cobranding.domain_listing_entity import DomainListing
from app.entity.domain.domain_marketplace_transaction_entity import DomainMarketplaceTransaction
from app.entity.payout.seller_payout_entity import SellerPayout
from app.entity.user.app_user import AppUser
from app.model.marketplace.transfer_mapper import build_transfer_response
from app.repository.domain_marketplace_transaction_repository import (
    DomainMarketplaceTransactionRepository,
)
from app.repository.seller_payout_profile_repository import SellerPayoutProfileRepository
from app.service.domain.domain_transfer_event_service import DomainTransferEventService
from app.service.payout.seller_payout_profile_service import SellerPayoutProfileService
from app.service.security.auth_code_encryption_service import decrypt_secret
from app.utils.transfer_enums import (
    MarketplaceEscrowStatus,
    MarketplaceTransferStatus,
    TransferEventType,
)

logger = logging.getLogger(__name__)


class DomainMarketplaceTransactionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DomainMarketplaceTransactionRepository(session)
        self._profiles = SellerPayoutProfileRepository(session)
        self._events = DomainTransferEventService(session)

    async def create_from_payment(
        self,
        listing: DomainListing,
        *,
        buyer: AppUser,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        commission_percent: float | None = None,
        gross_amount_inr: float | None = None,
    ) -> DomainMarketplaceTransaction:
        existing = await self._repo.get_by_razorpay_payment_id(razorpay_payment_id)
        if existing is not None:
            return existing

        seller_id = listing.listed_by_user_id
        if seller_id is None:
            raise AppException("Domain listing has no seller.", status_code=400)

        ext = listing.domain_extension or ""
        if ext and not ext.startswith("."):
            ext = f".{ext}"
        fqdn = f"{listing.domain_name}{ext}".lower()

        gross = float(
            gross_amount_inr
            if gross_amount_inr is not None
            else (listing.listing_price or listing.asking_price or 0)
        )
        if listing.seller_payout_amount is not None and listing.seller_payout_amount >= 0:
            seller_payout = float(listing.seller_payout_amount)
            platform_fee = float(listing.commission_amount or round(gross - seller_payout, 2))
        elif listing.seller_price is not None and listing.seller_price >= 0:
            # Backward compatibility for old rows where seller_price stores seller payout.
            seller_payout = float(listing.seller_price)
            platform_fee = round(gross - seller_payout, 2)
        else:
            pct = commission_percent
            if pct is None:
                stored = listing.commission_percentage
                if stored is not None:
                    pct = float(stored)
                else:
                    from app.service.platform.listing_pricing_service import ListingPricingService

                    pct = await ListingPricingService(self._session).commission_percent()
            platform_fee = round(gross * float(pct) / 100.0, 2)
            seller_payout = round(gross - platform_fee, 2)

        now = datetime.now(timezone.utc)
        seller_hours = settings.DOMAIN_TRANSFER_SELLER_DEADLINE_HOURS

        tx = DomainMarketplaceTransaction(
            domain_listing_id=listing.id,
            buyer_id=buyer.id,
            seller_id=seller_id,
            domain_fqdn=fqdn,
            gross_amount_inr=gross,
            platform_fee_inr=platform_fee,
            seller_payout_inr=seller_payout,
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            escrow_status=MarketplaceEscrowStatus.HELD,
            transfer_status=MarketplaceTransferStatus.AWAITING_AUTH_CODE,
            seller_deadline_at=now + timedelta(hours=seller_hours),
        )
        # Capture seller payout snapshot at creation time if profile exists.
        seller_profile = await self._profiles.get_by_user_id(seller_id)
        if seller_profile and SellerPayoutProfileService.is_complete(seller_profile):
            tx.payout_snapshot_method = seller_profile.payout_method.value if seller_profile.payout_method else None
            tx.payout_snapshot_account_holder = seller_profile.account_holder_name
            tx.payout_snapshot_bank_name = seller_profile.bank_name
            tx.payout_snapshot_ifsc = seller_profile.bank_ifsc
            tx.payout_snapshot_account_number = (seller_profile.account_number or "").strip() or None
            tx.payout_snapshot_account_last4 = seller_profile.account_number_last4
            try:
                tx.payout_snapshot_upi_id = decrypt_secret(seller_profile.upi_id_encrypted) if seller_profile.upi_id_encrypted else None
            except Exception:
                tx.payout_snapshot_upi_id = None
            tx.payout_snapshot_captured_at = now
            tx.payout_snapshot_source = "TRANSACTION_CREATION"

        tx = await self._repo.create(tx)
        listing.active_transaction_id = tx.id
        await self._events.log(
            tx.id,
            TransferEventType.PAYMENT_COMPLETED,
            actor_user_id=buyer.id,
            actor_role="BUYER",
            payload={"razorpayPaymentId": razorpay_payment_id},
        )
        return tx

    async def get_for_user(
        self,
        tx_id: uuid.UUID,
        user: AppUser,
        *,
        admin: bool = False,
    ) -> DomainMarketplaceTransaction:
        tx = await self._repo.get_by_id(tx_id)
        if tx is None:
            raise AppException("Transfer transaction not found.", status_code=404)
        if not admin and user.id not in (tx.buyer_id, tx.seller_id):
            raise AppException("Forbidden.", status_code=403)
        return tx

    async def serialize(
        self,
        tx: DomainMarketplaceTransaction,
        include_payout_profile: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = build_transfer_response(tx, **kwargs)
        if include_payout_profile:
            profile = await self._profiles.get_by_user_id(tx.seller_id)
            profile_complete = SellerPayoutProfileService.is_complete(profile)
            payout_profile_payload = (
                SellerPayoutProfileService(self._session)._serialize(profile) if profile else None
            )
            if profile and payout_profile_payload:
                full_account_number = (profile.account_number or "").strip()
                logger.info(
                    "admin.payout_profile.account_number seller_id=%s account_number=%s account_number_last4=%s",
                    tx.seller_id,
                    full_account_number or None,
                    profile.account_number_last4,
                )
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
                        "upiId": self._decrypt_optional(profile.upi_id_encrypted),
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
            else:
                logger.info(
                    "admin.payout_profile.account_number seller_id=%s account_number=%s account_number_last4=%s",
                    tx.seller_id,
                    None,
                    None,
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
                tx.payout_reminder_sent_at.isoformat() if tx.payout_reminder_sent_at else None
            )
            payload["payoutReminderCount"] = int(tx.payout_reminder_count or 0)
            payout_rows = (
                await self._session.execute(
                    select(SellerPayout)
                    .where(SellerPayout.transaction_id == tx.id)
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

    @staticmethod
    def _decrypt_optional(value: str | None) -> str | None:
        if not value:
            return None
        try:
            return decrypt_secret(value)
        except ValueError:
            return None
