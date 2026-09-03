import asyncio
from app.integrations.razorpay import client as rzp
from app.core.database import AsyncSessionLocal
from sqlalchemy import text

async def debug_line580():
    async with AsyncSessionLocal() as session:
        for pay_id in ['pay_TIUGsUqLzLZZed', 'pay_TIUDUIXfudt6Na', 'pay_TIU2uaObt20IhD']:
            pay = rzp.fetch_payment(pay_id)
            notes = pay.get("notes") or {}
            order_id = pay.get("order_id")
            order_notes = {}
            if order_id:
                try:
                    ord_obj = rzp.fetch_order(order_id)
                    order_notes = ord_obj.get("notes") or {}
                except Exception:
                    pass

            domain_name = str(notes.get("domainName") or notes.get("domain") or order_notes.get("domainName") or order_notes.get("domain") or "").strip()
            item_summary = str(order_notes.get("items_summary") or notes.get("items_summary") or "").strip()
            if item_summary:
                if item_summary.startswith("Domain Registration:"):
                    domain_name = item_summary.replace("Domain Registration:", "").strip()
                elif not domain_name and "." in item_summary and not item_summary.startswith("Venture") and not item_summary.startswith("Domain Addon"):
                    domain_name = item_summary

            buyer_email = str(order_notes.get("buyerEmail") or notes.get("buyerEmail") or notes.get("email") or pay.get("email") or "").strip()

            buyer_user_id = None
            if buyer_email:
                res_u = await session.execute(text("SELECT id FROM users WHERE email = :e LIMIT 1"), {"e": buyer_email})
                u = res_u.mappings().first()
                if u:
                    buyer_user_id = u.get("id")

            name_part, ext_part = (domain_name.split(".", 1) if "." in domain_name else (domain_name, ""))
            ext_full = ("." + ext_part) if ext_part else ""

            order_row = None
            if pay_id or (name_part and ext_full):
                sql_check = text("""
                    SELECT id, created_at, domain_name, domain_extension, buyer_full_name, buyer_email, buyer_phone, buyer_id,
                           price_inr, status, resellerclub_order_id, open_provider_domain_id, price_source, provision_message
                    FROM domain_registration_orders
                    WHERE razorpay_payment_id = :pay_id OR (domain_name = :dname AND domain_extension = :dext)
                """)
                res = await session.execute(sql_check, {"pay_id": pay_id, "dname": name_part, "dext": ext_full})
                order_row = res.mappings().first()

            print(f"PayID: {pay_id}")
            print(f"  order_row: {dict(order_row) if order_row else None}")
            print(f"  buyer_user_id: {buyer_user_id}")
            print(f"  domain_name: '{domain_name}' | name_part: '{name_part}' | ext_full: '{ext_full}'")
            print(f"  Condition line 580: not order_row={not order_row}, buyer_user_id={bool(buyer_user_id)}, name_part={bool(name_part)}, ext_full={bool(ext_full)}")

if __name__ == "__main__":
    asyncio.run(debug_line580())
