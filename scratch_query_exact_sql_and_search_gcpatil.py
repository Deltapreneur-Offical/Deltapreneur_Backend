import asyncio
from app.core.database import AsyncSessionLocal
from app.integrations.razorpay import client as rzp
from sqlalchemy import text

async def run_sql():
    async with AsyncSessionLocal() as session:
        print("=== 1. EXACT SQL QUERY ON domain_registration_orders ===")
        sql_dro = text("""
            SELECT id, domain_name, domain_extension, buyer_full_name, buyer_email, buyer_phone, razorpay_payment_id, razorpay_order_id, created_at
            FROM domain_registration_orders
            WHERE domain_name IN ('kundagol', 'hubballi', 'kmix')
        """)
        res_dro = await session.execute(sql_dro)
        dro_rows = res_dro.mappings().all()
        print(f"Found {len(dro_rows)} rows in domain_registration_orders:")
        for r in dro_rows:
            print("  ", dict(r))

        print("\n=== 2. EXACT SQL QUERY ON track_records ===")
        sql_tr = text("""
            SELECT id, internal_order_id, item_name, buyer_name, buyer_email, buyer_phone, razorpay_payment_id, razorpay_order_id, created_at
            FROM track_records
            WHERE item_name LIKE '%kundagol%' OR item_name LIKE '%hubballi%' OR item_name LIKE '%kmix%'
        """)
        res_tr = await session.execute(sql_tr)
        tr_rows = res_tr.mappings().all()
        print(f"Found {len(tr_rows)} rows in track_records:")
        for r in tr_rows:
            print("  ", dict(r))

        print("\n=== 3. SEARCHING FOR gcpatil2022@gmail.com IN users TABLE ===")
        res_u = await session.execute(text("SELECT id, email, firstname, lastname, phone_number FROM users WHERE email LIKE '%gcpatil%' OR firstname LIKE '%Goudappagouda%' OR lastname LIKE '%Patil%' OR phone_number LIKE '%9449842259%'"))
        u_rows = res_u.mappings().all()
        print(f"Found {len(u_rows)} matching users:")
        for u in u_rows:
            print("  ", dict(u))

        print("\n=== 4. RAZORPAY PAYMENT SEARCH FOR gcpatil2022@gmail.com OR 9449842259 ===")
        try:
            recent_pay = rzp.fetch_recent_payments(count=100)
            for p in recent_pay:
                email = str(p.get("email") or "").lower()
                contact = str(p.get("contact") or "")
                notes = str(p.get("notes") or "")
                if "gcpatil" in email or "9449842259" in contact or "gcpatil" in notes:
                    print("  Razorpay Match:", p)
        except Exception as exc:
            print("  Razorpay search error:", exc)

if __name__ == "__main__":
    asyncio.run(run_sql())
