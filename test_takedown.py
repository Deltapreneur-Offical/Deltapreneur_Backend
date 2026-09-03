import asyncio
import logging
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.entity.cocreation.software_auction import SoftwareAuction
from app.utils.enums import AuctionStatus

logging.basicConfig(level=logging.INFO)

async def main():
    async with AsyncSessionLocal() as session:
        try:
            stmt = select(SoftwareAuction).where(SoftwareAuction.status == AuctionStatus.TAKEN_DOWN)
            result = await session.execute(stmt)
            print("Query successful", len(result.scalars().all()))
        except Exception as e:
            print(f"Exception caught: {e}")

if __name__ == "__main__":
    asyncio.run(main())
