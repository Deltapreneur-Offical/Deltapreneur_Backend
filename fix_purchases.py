import asyncio
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from app.core.config import settings

async def main():
    engine = create_async_engine(settings.SQLALCHEMY_DATABASE_URI, echo=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        await session.execute(text("UPDATE software_purchases SET completion_status = 'CONFIRMED' WHERE completion_status = 'PENDING'"))
        await session.commit()
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
