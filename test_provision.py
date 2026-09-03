import asyncio
import uuid
import traceback
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Import app to trigger mapper registry of all classes
from app.main import app

from app.core.config import settings
from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
from app.service.domain.domain_registration_service import DomainRegistrationService

async def main():
    # Setup async engine
    engine = create_async_engine('postgresql+asyncpg://cobrotherpython:Aultum12345@database-1.cno8smi8qae3.ap-south-1.rds.amazonaws.com:5432/postgres')
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Load order
        order_id = uuid.UUID('c3ea899d-5399-4b04-ac5f-17d5f4603d05')
        service = DomainRegistrationService(session)
        order = await service._orders.get_by_id(order_id)
        if not order:
            print("Order not found")
            return
        
        # Reset attempts and status to retry provision
        order.status = 'PAYMENT_COMPLETED'
        
        print(f"Provisioning domain: {order.fqdn}")
        try:
            await service.provision_order(order)
            print("Provision success!")
            print("Status:", order.status)
            print("Message:", order.provision_message)
        except Exception as e:
            print("Provision failed with exception:")
            traceback.print_exc()
            print("Raw exception message:", str(e))

if __name__ == '__main__':
    asyncio.run(main())
