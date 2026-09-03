import asyncio
from sqlalchemy import select
from app.core.database import SessionLocal
from app.entity.auction.auction_entity import Auction
from app.entity.cobranding.domain_listing_entity import DomainListing

async def check():
    async with SessionLocal() as db:
        stmt = select(Auction, DomainListing).outerjoin(DomainListing, DomainListing.id == Auction.domain_id).where(DomainListing.domain_name == 'thisisaverylongdomainnamefortesting.com')
        result = await db.execute(stmt)
        for a, d in result.all():
            print(f"Auction {a.id}:")
            print(f"  created_at: {a.created_at}")
            print(f"  status: {a.status}")
            print(f"  start_time: {a.start_time}")
            print(f"  end_time: {a.end_time}")
            print(f"DomainListing {d.id}:")
            print(f"  created_at: {d.created_at}")
            print(f"  sale_type: {d.sale_type}")
            print(f"  verification_status: {d.verification_status}")
            print("-" * 40)

if __name__ == "__main__":
    asyncio.run(check())
