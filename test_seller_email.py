import asyncio
import logging
import sys
from app.core.database import SessionLocal
from app.entity.cocreation.software_purchase_entity import SoftwarePurchase
from app.entity.cocreation.software_entity import Software
from app.entity.user.app_user import AppUser
from app.service.cocreation.cocreation_payment_service import CocreationPaymentService

logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

async def main():
    async with SessionLocal() as session:
        user = AppUser(email="test_seller@example.com", firstname="Test", lastname="Seller")
        software = Software(name="Test Software", listed_by=user)
        purchase = SoftwarePurchase(buyer_full_name="Test Buyer", gross_amount_inr=100.0)
        
        service = CocreationPaymentService(session)
        print("Sending email...")
        await service._send_seller_sold_notification_email(purchase, software)
        print("Success!")

if __name__ == "__main__":
    asyncio.run(main())
