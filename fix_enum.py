import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()
db_url = os.getenv('DATABASE_URL')
if not db_url:
    print('DATABASE_URL not found')
else:
    db_url = db_url.replace('postgresql+asyncpg://', 'postgresql://')

async def main():
    if not db_url: return
    conn = await asyncpg.connect(db_url)
    try:
        await conn.execute("ALTER TYPE auction_status_enum ADD VALUE IF NOT EXISTS 'TAKEN_DOWN'")
        print('Enum value added!')
    except Exception as e:
        print('Error:', e)
    finally:
        await conn.close()

asyncio.run(main())
