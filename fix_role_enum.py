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
        await conn.execute("ALTER TYPE user_role_enum ADD VALUE IF NOT EXISTS 'SUPER_ADMIN'")
        print('Added SUPER_ADMIN')
    except Exception as e:
        print('Error 1:', e)
        
    try:
        await conn.execute("ALTER TYPE user_role_enum ADD VALUE IF NOT EXISTS 'AUCTION_MODERATOR'")
        print('Added AUCTION_MODERATOR')
    except Exception as e:
        print('Error 2:', e)
        
    finally:
        await conn.close()

asyncio.run(main())
