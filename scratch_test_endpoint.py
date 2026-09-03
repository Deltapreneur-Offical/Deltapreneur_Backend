import asyncio
from app.core.database import AsyncSessionLocal
from app.service.platform.track_record_service import TrackRecordService

async def test_api():
    async with AsyncSessionLocal() as session:
        tr_service = TrackRecordService(session)
        try:
            records, total = await tr_service.get_track_records(page=1, limit=50)
            print(f"Success! Total records count: {total}")
            print(f"Fetched {len(records)} records for page 1.")
            if records:
                print("First record sample:", records[0].to_dict())
        except Exception as exc:
            import traceback
            print("ERROR IN GET_TRACK_RECORDS:")
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_api())
