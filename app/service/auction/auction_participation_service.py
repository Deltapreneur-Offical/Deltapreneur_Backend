"""Participation fee flow for domain/software/community auctions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.auction.auction_participation_entity import (
    AuctionParticipation,
    AuctionParticipationStatus,
    AuctionParticipationType,
)
from app.entity.user.app_user import AppUser
from app.integrations.razorpay import client as rzp
from app.repository.auction_participation_repository import AuctionParticipationRepository
from app.repository.auction_repository import AuctionRepository
from app.entity.community.community_auction import CommunityAuction
from app.entity.cocreation.software_auction_participation_entity import (
    SoftwareAuctionParticipation,
    SoftwareAuctionParticipationStatus,
)
from app.repository.software_auction_participation_repository import (
    SoftwareAuctionParticipationRepository,
)
from app.repository.software_auction_repository import SoftwareAuctionRepository
from app.service.auction.domain_auction_guard import ensure_domain_verified_for_auction
from app.service.auction.auction_owner import is_auction_owner, owner_participation_status
from app.service.platform.platform_settings_service import PlatformSettingsService
from app.service.platform.platform_settings_service import DEFAULT_PARTICIPATION_FEE
from app.utils.enums import AuctionStatus


class AuctionParticipationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._rows = AuctionParticipationRepository(session)
        self._domain_auctions = AuctionRepository(session)
        self._software_auctions = SoftwareAuctionRepository(session)
        self._settings = PlatformSettingsService(session)

    async def _validate_auction_active_only(
        self, auction_type: AuctionParticipationType, auction_id: uuid.UUID
    ) -> None:
        """Auction must exist and be live — no domain verification gate."""
        if auction_type == AuctionParticipationType.DOMAIN:
            auction = await self._domain_auctions.get_auction_by_id(auction_id)
            if auction is None:
                raise AppException("Auction not found.", status_code=404)
            if auction.status not in (AuctionStatus.ACTIVE, AuctionStatus.EXTENDED):
                raise AppException("Auction is not active.", status_code=400)
            return
        if auction_type == AuctionParticipationType.SOFTWARE:
            auction = await self._software_auctions.get_by_id(auction_id)
            if auction is None:
                raise AppException("Auction not found.", status_code=404)
            if auction.status not in (AuctionStatus.ACTIVE, AuctionStatus.EXTENDED):
                raise AppException("Auction is not active.", status_code=400)
            return
        if auction_type == AuctionParticipationType.COMMUNITY:
            result = await self._session.execute(
                select(CommunityAuction).where(CommunityAuction.id == auction_id)
            )
            auction = result.scalar_one_or_none()
            if auction is None:
                raise AppException("Auction not found.", status_code=404)
            if auction.status not in ("ACTIVE", "EXTENDED"):
                raise AppException("Auction is not active.", status_code=400)
            return
        raise AppException("Unsupported auction type.", status_code=400)

    async def _validate_live_auction(
        self, auction_type: AuctionParticipationType, auction_id: uuid.UUID
    ) -> None:
        await self._validate_auction_active_only(auction_type, auction_id)
        if auction_type == AuctionParticipationType.DOMAIN:
            auction = await self._domain_auctions.get_auction_by_id(auction_id)
            if auction is not None:
                await ensure_domain_verified_for_auction(self._session, auction.domain_id)

    async def _fee_for_type(self, auction_type: AuctionParticipationType) -> float:
        if auction_type == AuctionParticipationType.DOMAIN:
            fee = await self._settings.domain_participation_fee_inr()
            return fee if fee and fee > 0 else DEFAULT_PARTICIPATION_FEE
        if auction_type == AuctionParticipationType.SOFTWARE:
            fee = await self._settings.software_participation_fee_inr()
            return fee if fee and fee > 0 else DEFAULT_PARTICIPATION_FEE
        if auction_type == AuctionParticipationType.COMMUNITY:
            fee = await self._settings.community_participation_fee_inr()
            return fee if fee and fee > 0 else DEFAULT_PARTICIPATION_FEE
        raise AppException("Unsupported auction type.", status_code=400)

    async def _software_participation_paid(
        self, auction_id: uuid.UUID, user_id: uuid.UUID
    ) -> bool:
        legacy = SoftwareAuctionParticipationRepository(self._session)
        return await legacy.has_completed(auction_id, user_id)

    async def _sync_software_participation_row(
        self,
        auction_id: uuid.UUID,
        user: AppUser,
        *,
        fee: float,
        razorpay_order_id: str,
        razorpay_payment_id: str,
    ) -> None:
        """Keep legacy software_auction_participations in sync with unified table."""
        legacy = SoftwareAuctionParticipationRepository(self._session)
        row = await legacy.get_by_auction_and_user(auction_id, user.id)
        if row is None:
            row = SoftwareAuctionParticipation(
                software_auction_id=auction_id,
                user_id=user.id,
                fee_amount_inr=fee,
                razorpay_order_id=razorpay_order_id,
                razorpay_payment_id=razorpay_payment_id,
                status=SoftwareAuctionParticipationStatus.COMPLETED,
            )
            await legacy.create(row)
            return
        row.status = SoftwareAuctionParticipationStatus.COMPLETED
        row.fee_amount_inr = fee
        row.razorpay_order_id = razorpay_order_id
        row.razorpay_payment_id = razorpay_payment_id
        row.updated_at = datetime.now(timezone.utc)
        await legacy.save(row)

    async def get_status(
        self, auction_type: AuctionParticipationType, auction_id: uuid.UUID, user: AppUser
    ) -> dict:
        await self._validate_auction_active_only(auction_type, auction_id)
        if await is_auction_owner(self._session, auction_type, auction_id, user.id):
            return owner_participation_status()

        fee = await self._fee_for_type(auction_type)
        bidding_blocked = False
        bidding_blocked_reason: str | None = None
        if auction_type == AuctionParticipationType.DOMAIN:
            auction = await self._domain_auctions.get_auction_by_id(auction_id)
            if auction is not None:
                try:
                    await ensure_domain_verified_for_auction(
                        self._session, auction.domain_id
                    )
                except AppException as exc:
                    bidding_blocked = True
                    bidding_blocked_reason = exc.message

        paid = await self._rows.has_completed(auction_type, auction_id, user.id)
        if not paid and auction_type == AuctionParticipationType.SOFTWARE:
            paid = await self._software_participation_paid(auction_id, user.id)
        return {
            "paid": True,
            "participationFeeInr": 0,
            "legacyParticipationPaid": paid,
            "canBid": not bidding_blocked,
            "isOwner": False,
            "biddingBlocked": bidding_blocked,
            "biddingBlockedReason": bidding_blocked_reason,
        }

    async def create_order(
        self, auction_type: AuctionParticipationType, auction_id: uuid.UUID, user: AppUser
    ) -> dict:
        raise AppException(
            "Participation fees are no longer required. Pay the per-bid fee when placing a bid.",
            status_code=410,
        )

    async def verify_payment(
        self,
        auction_type: AuctionParticipationType,
        auction_id: uuid.UUID,
        user: AppUser,
        *,
        razorpay_payment_id: str,
        razorpay_order_id: str,
        razorpay_signature: str,
    ) -> dict:
        if not rzp.verify_payment_signature(
            razorpay_order_id, razorpay_payment_id, razorpay_signature
        ):
            raise AppException("Invalid payment signature.", status_code=400)
        row = await self._rows.get_by_order_id(razorpay_order_id)
        if (
            row is None
            or row.auction_type != auction_type
            or row.auction_id != auction_id
            or row.user_id != user.id
        ):
            raise AppException("Participation record not found.", status_code=404)
        row.status = AuctionParticipationStatus.COMPLETED
        row.razorpay_payment_id = razorpay_payment_id
        row.updated_at = datetime.now(timezone.utc)
        await self._rows.save(row)
        if auction_type == AuctionParticipationType.SOFTWARE:
            await self._sync_software_participation_row(
                auction_id,
                user,
                fee=row.fee_amount_inr,
                razorpay_order_id=razorpay_order_id,
                razorpay_payment_id=razorpay_payment_id,
            )
        await self._session.commit()
        return {"paid": True, "message": "Participation fee confirmed. You can now place bids."}

    async def ensure_paid_or_raise(
        self, auction_type: AuctionParticipationType, auction_id: uuid.UUID, user: AppUser
    ) -> None:
        if await is_auction_owner(self._session, auction_type, auction_id, user.id):
            raise AppException("You cannot bid on your own auction.", status_code=403)
