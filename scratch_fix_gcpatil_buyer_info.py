import asyncio, uuid
from app.core.database import AsyncSessionLocal
from sqlalchemy import text

async def update_gcpatil():
    async with AsyncSessionLocal() as session:
        # 1. Check or insert user gcpatil2022@gmail.com
        res_u = await session.execute(text("SELECT id FROM users WHERE email = 'gcpatil2022@gmail.com'"))
        user_row = res_u.mappings().first()
        if user_row:
            gc_user_id = user_row["id"]
        else:
            gc_user_id = uuid.uuid4()
            sql_ins_user = text("""
                INSERT INTO users (id, email, firstname, lastname, phone_number, created_at, updated_at, role, is_active, email_verified)
                VALUES (:id, 'gcpatil2022@gmail.com', 'Goudappagouda', 'Patil', '9449842259', NOW(), NOW(), 'USER', true, true)
            """)
            await session.execute(sql_ins_user, {"id": gc_user_id})

        print(f"Goudappagouda Patil User ID: {gc_user_id}")

        # 2. Update domain_registration_orders
        sql_up_dro = text("""
            UPDATE domain_registration_orders
            SET buyer_full_name = 'Goudappagouda Patil',
                buyer_email = 'gcpatil2022@gmail.com',
                buyer_phone = '9449842259',
                buyer_id = :uid
            WHERE domain_name IN ('kundagol', 'hubballi', 'kmix')
        """)
        await session.execute(sql_up_dro, {"uid": gc_user_id})

        # 3. Update track_records
        sql_up_tr = text("""
            UPDATE track_records
            SET buyer_name = 'Goudappagouda Patil',
                buyer_email = 'gcpatil2022@gmail.com',
                buyer_phone = '9449842259',
                buyer_user_id = :uid
            WHERE item_name LIKE '%kundagol%' OR item_name LIKE '%hubballi%' OR item_name LIKE '%kmix%'
        """)
        await session.execute(sql_up_tr, {"uid": gc_user_id})

        await session.commit()
        print("Successfully updated buyer information to Goudappagouda Patil (gcpatil2022@gmail.com).")

        # 4. Print updated SQL results
        res_dro = await session.execute(text("SELECT domain_name, buyer_full_name, buyer_email, buyer_phone, razorpay_payment_id, created_at FROM domain_registration_orders WHERE domain_name IN ('kundagol', 'hubballi', 'kmix')"))
        print("\nUpdated domain_registration_orders:")
        for r in res_dro.mappings().all():
            print("  ", dict(r))

        res_tr = await session.execute(text("SELECT item_name, buyer_name, buyer_email, buyer_phone, razorpay_payment_id, created_at FROM track_records WHERE item_name LIKE '%kundagol%' OR item_name LIKE '%hubballi%' OR item_name LIKE '%kmix%'"))
        print("\nUpdated track_records:")
        for r in res_tr.mappings().all():
            print("  ", dict(r))

if __name__ == "__main__":
    asyncio.run(update_gcpatil())
