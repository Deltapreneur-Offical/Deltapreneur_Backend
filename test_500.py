import asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.core.database import async_engine
from app.service.platform.platform_settings_service import PlatformSettingsService

async def main():
    async_session = async_sessionmaker(async_engine, expire_on_commit=False)
    
    async with async_session() as session:
        service = PlatformSettingsService(session)
        try:
            print("Calling get_listing_fees_and_charges...")
            res = await service.get_listing_fees_and_charges()
            print("Success:", res)
        except Exception as e:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
