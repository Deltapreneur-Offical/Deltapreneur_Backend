import asyncio
import traceback
from app.core.database import SessionLocal, AsyncSessionLocal
from app.service.admin.admin_service import get_all_softwares_admin
from app.service.cocreation.software_auction_service import SoftwareAuctionService
import os
import sys

# add path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

async def run_tests():
    print("Testing get_all_softwares_admin...")
    db = SessionLocal()
    try:
        res = await get_all_softwares_admin(db)
        print("Success:", len(res["data"]))
    except Exception as e:
        print("Error in get_all_softwares_admin:")
        traceback.print_exc()
    finally:
        db.close()

    print("\nTesting list_pending_for_admin...")
    async with AsyncSessionLocal() as async_db:
        service = SoftwareAuctionService(async_db)
        try:
            res = await service.list_pending_for_admin()
            print("Success:", len(res))
        except Exception as e:
            print("Error in list_pending_for_admin:")
            traceback.print_exc()

    print("\nTesting list_all_for_admin...")
    async with AsyncSessionLocal() as async_db:
        service = SoftwareAuctionService(async_db)
        try:
            res = await service.list_all_for_admin()
            print("Success:", len(res))
        except Exception as e:
            print("Error in list_all_for_admin:")
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_tests())
