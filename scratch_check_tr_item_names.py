import asyncio
from app.core.database import AsyncSessionLocal
from sqlalchemy import text

async def check_tr_items():
    async with AsyncSessionLocal() as session:
        res = await session.execute(text("""
            SELECT id, item_name, category, provider_subcategory, razorpay_payment_id, buyer_name
            FROM track_records
            ORDER BY created_at DESC
        """))
        rows = res.mappings().all()
        print(f"=== TOTAL TRACK RECORDS: {len(rows)} ===")
        generic_count = 0
        for idx, r in enumerate(rows, 1):
            name = r['item_name']
            is_generic = name.startswith("Payment #") or name.startswith("Unprovisioned") or name == "Domain listing" or name == "Item"
            if is_generic:
                generic_count += 1
            print(f"{idx}. Name: '{name}' {'[GENERIC]' if is_generic else ''} | Category: {r['category']} | PaymentID: {r['razorpay_payment_id']} | Buyer: {r['buyer_name']}")
        print(f"\nTotal generic item names: {generic_count} / {len(rows)}")

if __name__ == "__main__":
    asyncio.run(check_tr_items())
