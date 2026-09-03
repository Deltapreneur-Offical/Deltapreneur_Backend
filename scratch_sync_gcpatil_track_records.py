"""
One-off: re-sync track_records for gcpatil2022@gmail.com
after manually fixing domain_registration_orders to ACTIVE.

This calls record_from_registration_order for each of the 3 orders,
which will update:
  - openprovider_domain_id   (was None, now 30053756 / 30053759 / 30053762)
  - fulfillment_status       (was FAILED, now PROVISIONED)
  - overall_status           (was FAILED/SUCCESS, now SUCCESS)
  - error_code / error_message  (cleared)
"""

import asyncio
from app.core.database import AsyncSessionLocal
from app.repository.domain_registration_order_repository import DomainRegistrationOrderRepository
from app.service.platform.track_record_service import TrackRecordService


PAYMENT_ID = "pay_TMnzSfhyUr1hr6"


async def run():
    async with AsyncSessionLocal() as session:
        repo = DomainRegistrationOrderRepository(session)
        orders = list(await repo.list_by_razorpay_payment_id(PAYMENT_ID))

        if not orders:
            print(f"No orders found for payment_id={PAYMENT_ID}")
            return

        print(f"Found {len(orders)} orders to sync:")
        for o in orders:
            print(f"  {o.domain_name}{o.domain_extension} | status={o.status} | op_id={o.open_provider_domain_id}")

        track_svc = TrackRecordService(session)
        synced = 0
        for order in orders:
            tr = await track_svc.record_from_registration_order(
                order,
                cart_batch_id=order.razorpay_order_id,
            )
            print(
                f"  Synced: {order.domain_name}{order.domain_extension} "
                f"-> track_record internal_id={tr.internal_order_id} "
                f"fulfillment={tr.fulfillment_status} overall={tr.overall_status} "
                f"op_id={tr.openprovider_domain_id} error={tr.error_code}"
            )
            synced += 1

        await session.commit()
        print(f"\nDone. Synced {synced} track records.")


if __name__ == "__main__":
    asyncio.run(run())
