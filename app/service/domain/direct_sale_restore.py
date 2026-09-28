"""Return an ended, unsold domain auction to a normal one-time listing."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.auction.auction_entity import Auction
from app.entity.cobranding.domain_listing_entity import DomainListing
from app.service.platform.listing_pricing_service import ListingPricingService
from app.utils.enums import AuctionStatus
from app.utils.listing_commission import compute_listing_commission
from app.utils.marketplace_enums import (
    DomainListingStatus,
    DomainListingVerificationStatus,
    SaleType,
)

# Auctions that finished without a completed sale. ENDED is not persisted today.
NO_SALE_AUCTION_STATUSES = {
    AuctionStatus.UNSOLD,
    AuctionStatus.CANCELLED,
    AuctionStatus.CLOSED,
    AuctionStatus.TAKEN_DOWN,
}


async def restore_listing_after_no_sale(
    session: AsyncSession,
    listing: DomainListing | None,
) -> bool:
    """Flip a finished no-sale auction back to a buyable one-time listing.

    Auction-only listings are created with asking_price 0; the seller's price
    lives on the auction as the minimum bid. That amount becomes the asking
    price when the auction ends with no sale. An asking price already stored
    on the listing is left as-is.
    """
    if listing is None or listing.domain_status == DomainListingStatus.SOLD:
        return False

    needs_sale_type = listing.sale_type == SaleType.AUCTION
    needs_price = float(listing.asking_price or 0) <= 0
    needs_verification = (
        listing.verification_status != DomainListingVerificationStatus.VERIFIED
        or not listing.verified
    )
    if not needs_sale_type and not needs_price and not needs_verification:
        if listing.domain_status == DomainListingStatus.AVAILABLE:
            return False

    result = await session.execute(
        select(Auction)
        .where(Auction.domain_id == listing.id, Auction.is_deleted.is_(False))
        .order_by(Auction.created_at.desc())
        .limit(1)
    )
    auction = result.scalar_one_or_none()
    if auction is None or auction.status not in NO_SALE_AUCTION_STATUSES:
        return False

    changed = False
    if listing.sale_type == SaleType.AUCTION:
        listing.sale_type = SaleType.ONE_TIME
        changed = True
    if listing.domain_status != DomainListingStatus.AVAILABLE:
        listing.domain_status = DomainListingStatus.AVAILABLE
        changed = True

    # A listing that already went to auction and ended unsold is not waiting
    # on a new admin review. Rejected listings stay rejected.
    if (
        auction.status == AuctionStatus.UNSOLD
        and listing.verification_status != DomainListingVerificationStatus.REJECTED
        and (
            listing.verification_status != DomainListingVerificationStatus.VERIFIED
            or not listing.verified
        )
    ):
        listing.verification_status = DomainListingVerificationStatus.VERIFIED
        listing.verified = True
        if listing.verified_at is None:
            listing.verified_at = datetime.now(timezone.utc)
        changed = True

    # Auction listings save the seller's price as the minimum bid and leave
    # asking_price at 0. Only an unsold auction may copy that stored bid
    # back. A price already on the listing is not replaced.
    if auction.status == AuctionStatus.UNSOLD and float(listing.asking_price or 0) <= 0:
        start_price = float(auction.min_bid_price or 0)
        if start_price > 0:
            percent = await ListingPricingService(session).commission_percent()
            seller, commission, final = compute_listing_commission(start_price, percent)
            listing.asking_price = final
            listing.listing_price = final
            listing.seller_price = seller
            listing.seller_payout_amount = seller
            listing.commission_percentage = percent
            listing.commission_amount = commission
            changed = True

    return changed
