import pytest
import uuid
from app.core.database import AsyncSessionLocal
from app.entity.user.app_user import AppUser
from app.entity.platform.track_record_entity import TrackRecord
from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
from app.service.platform.track_record_service import TrackRecordService, TrackRecordCategory, OverallStatus, FulfillmentStatus, PaymentStatus
from app.utils.registration_enums import RegistrationOrderStatus
from sqlalchemy import text

@pytest.mark.asyncio
async def test_track_records_service_create_and_query():
    async with AsyncSessionLocal() as session:
        service = TrackRecordService(session)
        
        pay_id = f"pay_test_{uuid.uuid4().hex[:12]}"
        ord_id = f"order_test_{uuid.uuid4().hex[:12]}"
        int_id = f"TRK-{ord_id}"
        
        # 1. Create track record
        record = await service.record_paid_attempt(
            internal_order_id=int_id,
            category=TrackRecordCategory.DOMAIN_MARKETPLACE,
            provider_subcategory="Razorpay",
            item_name="testmarketdomain.com",
            buyer_name="Test Buyer",
            buyer_email="buyer@example.com",
            amount_charged=15000.0,
            currency="INR",
            payment_status=PaymentStatus.CAPTURED,
            razorpay_order_id=ord_id,
            razorpay_payment_id=pay_id,
            fulfillment_status=FulfillmentStatus.PROVISIONED,
            overall_status=OverallStatus.SUCCESS,
        )
        
        assert record is not None
        assert record.item_name == "testmarketdomain.com"
        assert record.category == TrackRecordCategory.DOMAIN_MARKETPLACE
        assert record.overall_status == OverallStatus.SUCCESS

        # 2. Query admin records
        records, total = await service.list_admin_records(
            search_term="testmarketdomain.com",
            page=1,
            limit=10
        )
        assert total >= 1
        assert any(r.razorpay_payment_id == pay_id for r in records)

        # Cleanup
        await session.execute(text("DELETE FROM track_records WHERE razorpay_payment_id = :p"), {"p": pay_id})
        await session.commit()

@pytest.mark.asyncio
async def test_track_records_service_from_domain_order():
    async with AsyncSessionLocal() as session:
        service = TrackRecordService(session)

        pay_id = f"pay_test_order_{uuid.uuid4().hex[:12]}"
        ord_id = f"order_test_order_{uuid.uuid4().hex[:12]}"
        buyer_email = f"opbuyer-{uuid.uuid4().hex[:8]}@example.com"

        buyer = AppUser(
            email=buyer_email,
            firstname="OpenProvider",
            lastname="Buyer",
            active=True,
            email_verified=True,
            profile_complete=True,
        )
        session.add(buyer)
        await session.flush()

        order = DomainRegistrationOrder(
            domain_name="testopenprovider",
            domain_extension=".com",
            buyer_id=buyer.id,
            buyer_full_name="OpenProvider Buyer",
            buyer_email=buyer_email,
            buyer_phone="9988776655",
            price_inr=1200.0,
            price_source="cart_checkout",
            status=RegistrationOrderStatus.ACTIVE,
            razorpay_order_id=ord_id,
            razorpay_payment_id=pay_id,
            open_provider_domain_id="op-test-12345",
        )
        session.add(order)
        await session.commit()

        record = await service.record_from_registration_order(order)
        assert record is not None
        assert record.item_name == "testopenprovider.com"
        assert record.category == TrackRecordCategory.DOMAIN_REGISTRATION_OPENPROVIDER
        assert record.overall_status == OverallStatus.SUCCESS

        # Cleanup
        await session.execute(text("DELETE FROM track_records WHERE razorpay_payment_id = :p"), {"p": pay_id})
        await session.execute(text("DELETE FROM domain_registration_orders WHERE razorpay_payment_id = :p"), {"p": pay_id})
        await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": buyer.id})
        await session.commit()
