"""Admin verification workflow for domain auction listings."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.auction.domain_entity import Domain
from app.entity.user.app_user import AppUser
from app.repository.auction_repository import AuctionRepository
from app.repository.domain_listing_repository import DomainListingRepository
from app.repository.domain_repository import DomainRepository
from app.service.admin.admin_serializers import user_brief
from app.utils.domain_listing_utils import listing_type_for
from app.utils.enums import AuctionStatus
from app.utils.marketplace_enums import (
    DomainListingVerificationStatus,
    SaleType,
)


def is_auction_publicly_visible(
    listing: Any | None,
) -> bool:
    """Whether an auction linked to this listing may appear on public browse."""
    if listing is None:
        return True
    if listing.sale_type != SaleType.AUCTION:
        return True
    return listing.verification_status == DomainListingVerificationStatus.VERIFIED


class DomainAuctionVerificationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._listings = DomainListingRepository(session)
        self._auctions = AuctionRepository(session)
        self._domains = DomainRepository(session)

    async def _get_listing(self, listing_id: uuid.UUID):
        listing = await self._listings.get_by_id(listing_id)
        if listing is None or listing.is_deleted:
            raise AppException("Domain listing not found.", status_code=404)
        return listing

    def _serialize_auction(self, auction) -> dict[str, Any] | None:
        if auction is None:
            return None
        duration = auction.duration
        duration_val = duration.value if hasattr(duration, "value") else duration
        status_val = auction.status.value if hasattr(auction.status, "value") else auction.status
        return {
            "id": str(auction.id),
            "status": status_val,
            "minBidPrice": float(auction.min_bid_price),
            "duration": duration_val,
            "startTime": auction.start_time.isoformat() if auction.start_time else None,
            "endTime": auction.end_time.isoformat() if auction.end_time else None,
            "totalBids": int(auction.total_bids or 0),
            "currentHighestBid": (
                float(auction.current_highest_bid)
                if auction.current_highest_bid is not None
                else None
            ),
        }

    async def get_review_payload(self, listing_id: uuid.UUID) -> dict[str, Any]:
        listing = await self._get_listing(listing_id)
        auction = await self._auctions.get_auction_by_domain(listing_id)
        verification_method = (
            listing.verification_method.value
            if listing.verification_method is not None
            and hasattr(listing.verification_method, "value")
            else listing.verification_method
        )
        verification_status = (
            listing.verification_status.value
            if hasattr(listing.verification_status, "value")
            else listing.verification_status
        )
        sale_type = (
            listing.sale_type.value
            if hasattr(listing.sale_type, "value")
            else listing.sale_type
        )
        return {
            "id": str(listing.id),
            "domainName": listing.domain_name,
            "domainExtension": listing.domain_extension or "",
            "listingType": listing_type_for(listing.sale_type),
            "saleType": sale_type,
            "verified": bool(listing.verified),
            "verificationMethod": verification_method,
            "verifiedAt": listing.verified_at.isoformat() if listing.verified_at else None,
            "whoisEmail": listing.whois_email,
            "verificationStatus": verification_status,
            "verificationRejectionReason": listing.verification_rejection_reason,
            "verificationAdminNote": listing.verification_admin_note,
            "verifiedBy": user_brief(listing.verified_by),
            "listedBy": user_brief(listing.listed_by),
            "auction": self._serialize_auction(auction),
        }

    async def _notify_seller(
        self,
        listing,
        *,
        title: str,
        message: str,
        target_url: str,
    ) -> None:
        owner = listing.listed_by
        if owner is None:
            return
        try:
            from app.core.database import SessionLocal
            from app.entity.notification.notification_type import NotificationType
            from app.service.notification.notification_service import NotificationService

            db = SessionLocal()
            try:
                NotificationService.notify(
                    db=db,
                    user=owner,
                    notification_type=NotificationType.DOMAIN_VERIFIED,
                    title=title,
                    message=message,
                    target_url=target_url,
                )
            finally:
                db.close()
        except Exception:
            pass

    async def _sync_domain_registry_verified(self, listing_id: uuid.UUID) -> None:
        domain = await self._domains.get_by_id_alive(listing_id)
        if domain is not None:
            domain.is_verified = True
            await self._session.flush()

    async def approve_and_go_live(
        self,
        listing_id: uuid.UUID,
        *,
        admin: AppUser,
    ) -> dict[str, Any]:
        listing = await self._get_listing(listing_id)
        if listing.sale_type != SaleType.AUCTION:
            raise AppException(
                "Approve & Go Live applies only to auction domain listings.",
                status_code=400,
            )
        if listing.verification_status not in {
            DomainListingVerificationStatus.PENDING,
            DomainListingVerificationStatus.MORE_INFO_REQUESTED,
        }:
            raise AppException(
                "Listing is not awaiting admin verification approval.",
                status_code=400,
            )

        auction = await self._auctions.get_auction_by_domain(listing_id)
        if auction is None:
            raise AppException(
                "No auction found for this domain listing. "
                "The seller may not have completed auction payment during listing.",
                status_code=400,
            )
        if auction.status not in {AuctionStatus.DRAFT, AuctionStatus.CANCELLED}:
            if auction.status in {AuctionStatus.ACTIVE, AuctionStatus.EXTENDED}:
                if listing.verification_status != DomainListingVerificationStatus.VERIFIED:
                    listing.verification_status = DomainListingVerificationStatus.VERIFIED
                    listing.verified = True
                    listing.verified_by_user_id = admin.id
                    listing.verified_at = datetime.now(timezone.utc)
                    await self._listings.save(listing)
                    await self._session.commit()
                return await self.get_review_payload(listing_id)
            raise AppException(
                "Auction cannot be published from its current state.",
                status_code=400,
            )

        now = datetime.now(timezone.utc)
        end_time = now + timedelta(seconds=auction.duration.to_seconds())

        listing.verification_status = DomainListingVerificationStatus.VERIFIED
        listing.verified = True
        listing.verified_at = now
        listing.verified_by_user_id = admin.id
        listing.verification_admin_note = None
        listing.verification_rejection_reason = None
        listing.updated_at = now

        auction.status = AuctionStatus.ACTIVE
        auction.start_time = now
        auction.end_time = end_time
        auction.original_end_time = end_time

        await self._listings.save(listing)
        await self._session.flush()
        await self._sync_domain_registry_verified(listing_id)
        await self._session.commit()

        label = f"{listing.domain_name}{listing.domain_extension}".strip()
        await self._notify_seller(
            listing,
            title="Domain auction approved",
            message=f"{label} is now live on the auction marketplace.",
            target_url=f"/auction/{auction.id}",
        )

        return await self.get_review_payload(listing_id)

    async def reject_verification(
        self,
        listing_id: uuid.UUID,
        *,
        admin: AppUser,
        reason: str,
    ) -> dict[str, Any]:
        listing = await self._get_listing(listing_id)
        if listing.sale_type != SaleType.AUCTION:
            raise AppException(
                "Reject verification applies only to auction domain listings.",
                status_code=400,
            )
        cleaned = (reason or "").strip()
        if not cleaned:
            raise AppException("Rejection reason is required.", status_code=400)

        listing.verification_status = DomainListingVerificationStatus.REJECTED
        listing.verification_rejection_reason = cleaned
        listing.verification_admin_note = None
        listing.updated_at = datetime.now(timezone.utc)

        auction = await self._auctions.get_auction_by_domain(listing_id)
        if auction is not None and auction.status in {
            AuctionStatus.DRAFT,
            AuctionStatus.ACTIVE,
            AuctionStatus.EXTENDED,
        }:
            auction.status = AuctionStatus.CANCELLED
            await self._session.flush()

        await self._listings.save(listing)
        await self._session.commit()

        label = f"{listing.domain_name}{listing.domain_extension}".strip()
        await self._notify_seller(
            listing,
            title="Domain auction verification rejected",
            message=f"{label}: {cleaned}",
            target_url="/domains/dashboard",
        )

        return await self.get_review_payload(listing_id)

    async def request_more_information(
        self,
        listing_id: uuid.UUID,
        *,
        admin: AppUser,
        message: str,
    ) -> dict[str, Any]:
        listing = await self._get_listing(listing_id)
        if listing.sale_type != SaleType.AUCTION:
            raise AppException(
                "Request more information applies only to auction domain listings.",
                status_code=400,
            )
        cleaned = (message or "").strip()
        if not cleaned:
            raise AppException("Message is required.", status_code=400)

        listing.verification_status = DomainListingVerificationStatus.MORE_INFO_REQUESTED
        listing.verification_admin_note = cleaned
        listing.updated_at = datetime.now(timezone.utc)

        await self._listings.save(listing)
        await self._session.commit()

        label = f"{listing.domain_name}{listing.domain_extension}".strip()
        await self._notify_seller(
            listing,
            title="More information needed",
            message=f"{label}: {cleaned}",
            target_url="/domains/dashboard",
        )

        return await self.get_review_payload(listing_id)
