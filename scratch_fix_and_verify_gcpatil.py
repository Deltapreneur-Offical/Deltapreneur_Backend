import asyncio
from app.core.database import AsyncSessionLocal
from sqlalchemy import text

async def run_fix():
    async with AsyncSessionLocal() as session:
        gc_user_id = 'af070795-086d-4dbe-9636-ebde69d60e1d'
        gc_email = 'gcpatil2022@gmail.com'
        gc_name = 'Goudappagouda Patil'
        gc_phone = '9449842259'

        # 1. Update domain_registration_orders
        sql_dro = text("""
            UPDATE domain_registration_orders
            SET buyer_full_name = :bname,
                buyer_email = :bemail,
                buyer_phone = :bphone,
                buyer_id = :uid
            WHERE domain_name LIKE '%kundagol%' OR domain_name LIKE '%hubballi%' OR domain_name LIKE '%kmix%'
        """)
        res1 = await session.execute(sql_dro, {
            "bname": gc_name,
            "bemail": gc_email,
            "bphone": gc_phone,
            "uid": gc_user_id
        })
        print(f"Updated {res1.rowcount} rows in domain_registration_orders.")

        # 2. Update track_records
        sql_tr = text("""
            UPDATE track_records
            SET buyer_name = :bname,
                buyer_email = :bemail,
                buyer_phone = :bphone,
                buyer_user_id = :uid
            WHERE item_name LIKE '%kundagol%' OR item_name LIKE '%hubballi%' OR item_name LIKE '%kmix%'
        """)
        res2 = await session.execute(sql_tr, {
            "bname": gc_name,
            "bemail": gc_email,
            "bphone": gc_phone,
            "uid": gc_user_id
        })
        print(f"Updated {res2.rowcount} rows in track_records.")

        await session.commit()

        # 3. Print exact SQL results requested by user
        print("\n=== EXACT SQL RESULT FOR domain_registration_orders ===")
        sql_sel1 = text("""
            SELECT domain_name, domain_extension, buyer_full_name, buyer_email, buyer_phone, razorpay_payment_id, razorpay_order_id, created_at
            FROM domain_registration_orders
            WHERE domain_name LIKE '%kundagol%' OR domain_name LIKE '%hubballi%' OR domain_name LIKE '%kmix%'
        """)
        r1 = await session.execute(sql_sel1)
        for row in r1.mappings().all():
            print("  ", dict(row))

        print("\n=== EXACT SQL RESULT FOR track_records ===")
        sql_sel2 = text("""
            SELECT item_name, buyer_name, buyer_email, buyer_phone, razorpay_payment_id, razorpay_order_id, created_at
            FROM track_records
            WHERE item_name LIKE '%kundagol%' OR item_name LIKE '%hubballi%' OR item_name LIKE '%kmix%'
        """)
        r2 = await session.execute(sql_sel2)
        for row in r2.mappings().all():
            print("  ", dict(row))

if __name__ == "__main__":
    asyncio.run(run_fix())
