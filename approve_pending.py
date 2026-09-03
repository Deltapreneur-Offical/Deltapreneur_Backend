import asyncio
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import SessionLocal
from app.entity.auction.auction_entity import Auction
from app.entity.cobranding.domain_listing_entity import DomainListing
from app.utils.enums import AuctionStatus
from app.utils.marketplace_enums import DomainListingVerificationStatus, SaleType

async def approve_all_pending():
    async with SessionLocal() as db:
        # Find all pending domain listings that are auctions
        stmt = select(DomainListing).where(
            DomainListing.sale_type == SaleType.AUCTION,
            DomainListing.verification_status == DomainListingVerificationStatus.PENDING
        )
        result = await db.execute(stmt)
        listings = result.scalars().all()
        
        if not listings:
            print("No pending domain auctions found.")
            return

        now = datetime.now(timezone.utc)
        for listing in listings:
            print(f"Approving domain listing: {listing.domain_name}")
            listing.verification_status = DomainListingVerificationStatus.VERIFIED
            listing.verified = True
            listing.verified_at = now
            listing.verification_admin_note = "Auto-approved for testing"
            
            # Find the corresponding draft auction
            auction_stmt = select(Auction).where(
                Auction.domain_id == listing.id,
                Auction.status == AuctionStatus.DRAFT
            )
            auction_result = await db.execute(auction_stmt)
            auction = auction_result.scalar_one_or_none()
            
            if auction:
                print(f"Activating auction {auction.id} for {listing.domain_name}")
                auction.status = AuctionStatus.ACTIVE
                auction.start_time = now
                # Adjust end time relative to now
                from datetime import timedelta
                auction.end_time = now + timedelta(seconds=auction.duration.to_seconds())
                auction.original_end_time = auction.end_time
                db.add(auction)
            
            db.add(listing)
            
        await db.commit()
        print("Done approving!")

if __name__ == "__main__":
    asyncio.run(approve_all_pending())
