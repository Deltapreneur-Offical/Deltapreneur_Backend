"""Cart checkout helpers for DOMAIN_REGISTRATION registrant + revalidation."""

from __future__ import annotations

import pytest

from app.core.exceptions import AppException
from app.service.cart.cart_checkout_service import CartCheckoutService


def test_require_registrant_rejects_missing_fields():
    with pytest.raises(AppException) as exc:
        CartCheckoutService._require_registrant({"firstName": "A"})
    assert exc.value.status_code == 400
    assert "lastName" in exc.value.message


def test_require_registrant_accepts_complete():
    CartCheckoutService._require_registrant(
        {
            "firstName": "A",
            "lastName": "B",
            "email": "a@b.com",
            "phone": "9876543210",
            "street": "1 St",
            "city": "Delhi",
            "state": "DL",
            "zip": "110001",
        }
    )


@pytest.mark.asyncio
async def test_remove_fulfilled_cart_items_for_payment_filtering():
    import uuid
    from unittest.mock import AsyncMock, MagicMock
    from app.utils.cart_enums import CartProductType

    session = AsyncMock()
    service = CartCheckoutService(session)
    buyer_id = uuid.uuid4()
    order_id = "order_rzp_123"

    item_fulfilled = MagicMock()
    item_fulfilled.id = uuid.uuid4()
    item_fulfilled.product_type = CartProductType.DOMAIN_REGISTRATION
    item_fulfilled.metadata_json = {"_checkout_razorpay_order_id": order_id, "domainName": "buy1.com"}

    item_other = MagicMock()
    item_other.id = uuid.uuid4()
    item_other.product_type = CartProductType.TECHNOLOGY
    item_other.metadata_json = {"_checkout_razorpay_order_id": "order_other_456"}

    service._repo.get_by_user = AsyncMock(return_value=[item_fulfilled, item_other])
    service._repo.delete_items_by_ids = AsyncMock(return_value=1)

    deleted = await service.remove_fulfilled_cart_items_for_payment(buyer_id, razorpay_order_id=order_id)
    assert deleted == 1
    service._repo.delete_items_by_ids.assert_called_once_with([item_fulfilled.id], buyer_id)


@pytest.mark.asyncio
async def test_cleanup_stale_purchased_cart_items():
    import uuid
    from unittest.mock import AsyncMock, MagicMock
    from app.service.cart.cart_service import CartService
    from app.utils.cart_enums import CartProductType
    from app.utils.registration_enums import RegistrationOrderStatus

    session = AsyncMock()
    cart_svc = CartService(session)
    user_id = uuid.uuid4()

    item_stale = MagicMock()
    item_stale.id = uuid.uuid4()
    item_stale.product_type = CartProductType.DOMAIN_REGISTRATION
    item_stale.metadata_json = {"domainName": "alreadyowned.com"}

    item_active_unpaid = MagicMock()
    item_active_unpaid.id = uuid.uuid4()
    item_active_unpaid.product_type = CartProductType.DOMAIN_REGISTRATION
    item_active_unpaid.metadata_json = {"domainName": "newunpaid.com"}

    cart_svc._repo.get_by_user = AsyncMock(return_value=[item_stale, item_active_unpaid])
    cart_svc._repo.delete_items_by_ids = AsyncMock(return_value=1)

    order_owned = MagicMock()
    order_owned.id = uuid.uuid4()
    order_owned.domain_name = "alreadyowned"
    order_owned.domain_extension = ".com"
    order_owned.status = RegistrationOrderStatus.ACTIVE

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [order_owned]
    mock_res = MagicMock()
    mock_res.scalars.return_value = mock_scalars

    session.execute = AsyncMock(return_value=mock_res)

    deleted = await cart_svc.cleanup_stale_purchased_cart_items(user_id)
    assert deleted == 1
    cart_svc._repo.delete_items_by_ids.assert_called_once_with([item_stale.id], user_id)


@pytest.mark.asyncio
async def test_cart_cleanup_survives_pending_rollback_and_zero_rows():
    import uuid
    from unittest.mock import AsyncMock
    from sqlalchemy.exc import PendingRollbackError

    session = AsyncMock()
    session.rollback = AsyncMock()
    service = CartCheckoutService(session)
    service._repo.get_by_user = AsyncMock(
        side_effect=[
            PendingRollbackError("Can't reconnect until invalid transaction is rolled back"),
            [],
        ]
    )
    service._repo.delete_items_by_ids = AsyncMock(return_value=0)

    deleted = await service.remove_fulfilled_cart_items_for_payment(
        uuid.uuid4(),
        razorpay_order_id="order_rzp_empty",
        domains=["hubregistrar.in"],
    )
    assert deleted == 0
    session.rollback.assert_awaited()
    service._repo.delete_items_by_ids.assert_not_called()


@pytest.mark.asyncio
async def test_recover_pending_active_order_is_success_not_failed():
    import uuid
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.utils.registration_enums import RegistrationOrderStatus

    session = AsyncMock()
    service = CartCheckoutService(session)
    buyer = MagicMock()
    buyer.id = uuid.uuid4()

    order = MagicMock()
    order.id = uuid.uuid4()
    order.buyer_id = buyer.id
    order.domain_name = "hubregistrar"
    order.domain_extension = ".in"
    order.status = RegistrationOrderStatus.ACTIVE
    order.razorpay_payment_id = "pay_live_1"

    mock_repo = AsyncMock()
    mock_repo.list_by_razorpay_order_id = AsyncMock(return_value=[order])

    with (
        patch(
            "app.repository.domain_registration_order_repository.DomainRegistrationOrderRepository",
            return_value=mock_repo,
        ),
        patch(
            "app.service.domain.domain_registration_service.DomainRegistrationService",
        ) as mock_svc_cls,
    ):
        results = await service._provision_pending_orders_for_payment(
            buyer=buyer,
            razorpay_order_id="order_rzp_1",
            razorpay_payment_id="pay_live_1",
        )

    assert results[0]["success"] is True
    assert results[0]["alreadyProcessed"] is True
    assert results[0]["status"] == "ACTIVE"
    mock_svc_cls.return_value.provision_order.assert_not_called()


@pytest.mark.asyncio
async def test_recover_pending_rollback_does_not_mark_active_failed():
    import uuid
    from unittest.mock import AsyncMock, MagicMock, patch
    from sqlalchemy.exc import PendingRollbackError
    from app.utils.registration_enums import RegistrationOrderStatus

    session = AsyncMock()
    session.rollback = AsyncMock()
    service = CartCheckoutService(session)
    buyer = MagicMock()
    buyer.id = uuid.uuid4()

    order = MagicMock()
    order.id = uuid.uuid4()
    order.buyer_id = buyer.id
    order.domain_name = "hubregistrar"
    order.domain_extension = ".in"
    order.status = RegistrationOrderStatus.PAYMENT_COMPLETED
    order.razorpay_payment_id = "pay_live_1"

    active = MagicMock()
    active.id = order.id
    active.status = RegistrationOrderStatus.ACTIVE
    active.domain_name = "hubregistrar"
    active.domain_extension = ".in"

    mock_repo = AsyncMock()
    mock_repo.list_by_razorpay_order_id = AsyncMock(return_value=[order])
    mock_repo.save = AsyncMock()
    mock_repo.get_by_id = AsyncMock(
        side_effect=[
            PendingRollbackError("Can't reconnect until invalid transaction is rolled back"),
            active,
        ]
    )

    mock_svc = MagicMock()
    mock_svc.provision_order = AsyncMock(side_effect=RuntimeError("registrar timeout"))

    with (
        patch(
            "app.repository.domain_registration_order_repository.DomainRegistrationOrderRepository",
            return_value=mock_repo,
        ),
        patch(
            "app.service.domain.domain_registration_service.DomainRegistrationService",
            return_value=mock_svc,
        ),
    ):
        results = await service._provision_pending_orders_for_payment(
            buyer=buyer,
            razorpay_order_id="order_rzp_1",
            razorpay_payment_id="pay_live_1",
        )

    assert results[0]["success"] is True
    assert results[0]["status"] == "ACTIVE"
    assert order.status != RegistrationOrderStatus.PROVISION_FAILED
    session.rollback.assert_awaited()


