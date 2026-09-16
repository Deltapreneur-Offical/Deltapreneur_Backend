"""Technology marketplace payment recovery, payout, and refund guards."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AppException
from app.service.cocreation.cocreation_payment_service import (
    CocreationPaymentService,
    should_mark_listing_sold,
)
from app.service.cocreation.technology_transfer_payout_service import (
    TechnologyTransferPayoutService,
)
from app.service.cocreation.technology_verification_guard import (
    assert_technology_purchasable,
)
from app.utils.cocreation_enums import (
    SoftwarePaymentStatus,
    SoftwarePurchaseCompletionStatus,
    SoftwarePurchaseType,
    SoftwareStatus,
    TechnologyPricingPlanDuration,
)


def _software(**kwargs):
    defaults = dict(
        id=uuid.uuid4(),
        listed_by_user_id=uuid.uuid4(),
        verified=True,
        rejected=False,
        software_status=SoftwareStatus.AVAILABLE,
        purchase_type=SoftwarePurchaseType.ONE_TIME,
        price=100.0,
        github_link="https://github.com/org/repo",
        documentation_urls="https://docs.example",
        download_urls=None,
        name="Tool",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_create_purchase_order_blocks_rejected_listing(monkeypatch):
    software = _software(verified=True, rejected=True)
    session = AsyncMock()
    service = CocreationPaymentService(session)
    service._software_repo = AsyncMock()
    service._software_repo.get_by_id = AsyncMock(return_value=software)
    service._purchase_repo = AsyncMock()
    service._purchase_repo.has_completed_purchase = AsyncMock(return_value=False)
    buyer = MagicMock()
    buyer.id = uuid.uuid4()
    monkeypatch.setattr(
        "app.service.cocreation.cocreation_payment_service.settings.REQUIRE_TECHNOLOGY_VERIFICATION_BEFORE_PURCHASE",
        True,
    )
    with pytest.raises(AppException, match="rejected"):
        await service.create_purchase_order(software.id, buyer=buyer)


def test_assert_purchasable_allows_verified():
    assert_technology_purchasable(_software(verified=True, rejected=False))


def test_subscription_is_not_exclusive_sale():
    purchase = SimpleNamespace(selected_plan=TechnologyPricingPlanDuration.ONE_MONTH)
    software = _software(purchase_type=SoftwarePurchaseType.SUBSCRIPTION)
    assert should_mark_listing_sold(software, purchase) is False


@pytest.mark.asyncio
async def test_handle_failure_does_not_downgrade_paid_row():
    purchase = SimpleNamespace(
        payment_status=SoftwarePaymentStatus.CREATED,
        razorpay_payment_id="pay_1",
    )
    session = AsyncMock()
    service = CocreationPaymentService(session)
    service._purchase_repo = AsyncMock()
    service._purchase_repo.find_latest_created = AsyncMock(return_value=purchase)
    buyer = MagicMock()
    buyer.id = uuid.uuid4()
    await service.handle_failure(uuid.uuid4(), buyer=buyer)
    service._purchase_repo.save.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_completes_created_purchase():
    software = _software()
    purchase = SimpleNamespace(
        id=uuid.uuid4(),
        software_id=software.id,
        buyer_id=uuid.uuid4(),
        payment_status=SoftwarePaymentStatus.CREATED,
        completion_status=SoftwarePurchaseCompletionStatus.PENDING,
        razorpay_order_id="order_1",
        razorpay_payment_id=None,
        co_brother_opt_in=False,
        selected_plan=None,
        expiry_date=None,
        delivered_at=None,
        delivered_github_link=None,
        purchase_addon_services=None,
        buyer_full_name="Buyer",
        buyer_email="b@test.local",
        buyer_phone="9999999999",
        gross_amount_inr=100.0,
        software=software,
    )
    session = AsyncMock()
    service = CocreationPaymentService(session)
    service._purchase_repo = AsyncMock()
    service._purchase_repo.list_by_razorpay_order_id_for_update = AsyncMock(
        return_value=[purchase]
    )
    service._purchase_repo.save = AsyncMock()
    service._software_repo = AsyncMock()
    service._create_cobrother_request = AsyncMock()
    service._send_receipt_email = AsyncMock()
    service._send_seller_sold_notification_email = AsyncMock()
    monkeypatch_track = AsyncMock()
    from unittest.mock import patch

    with patch(
        "app.utils.addon_services.create_addon_operations_requests",
        new=AsyncMock(),
    ), patch(
        "app.service.platform.track_record_service.TrackRecordService",
        return_value=SimpleNamespace(record_paid_attempt=monkeypatch_track),
    ):
        result = await service.complete_from_webhook("order_1", "pay_1")
    assert result["purchasesFound"] == 1
    assert result["purchasesCompleted"] == 1
    assert purchase.payment_status == SoftwarePaymentStatus.COMPLETED
    assert purchase.delivered_github_link == software.github_link


@pytest.mark.asyncio
async def test_payout_blocks_unpaid_and_refunded():
    session = AsyncMock()
    svc = TechnologyTransferPayoutService(session)
    unpaid = SimpleNamespace(
        seller_paid_at=None,
        payment_status=SoftwarePaymentStatus.FAILED,
        refund_completed_at=None,
        software=_software(),
    )
    with pytest.raises(AppException, match="failed"):
        await svc._assert_payout_eligible(unpaid)
    refunded = SimpleNamespace(
        seller_paid_at=None,
        payment_status=SoftwarePaymentStatus.REFUNDED,
        refund_completed_at=None,
        software=_software(),
    )
    with pytest.raises(AppException, match="refunded"):
        await svc._assert_payout_eligible(refunded)


@pytest.mark.asyncio
async def test_admin_refund_blocks_released_payout():
    session = AsyncMock()
    service = CocreationPaymentService(session)
    purchase = SimpleNamespace(
        payment_status=SoftwarePaymentStatus.COMPLETED,
        seller_paid_at="already",
        refund_completed_at=None,
        razorpay_payment_id="pay_1",
        gross_amount_inr=100,
    )
    service._purchase_repo = AsyncMock()
    service._purchase_repo.get_by_id_for_update = AsyncMock(return_value=purchase)
    admin = MagicMock()
    admin.id = uuid.uuid4()
    with pytest.raises(AppException, match="seller paid"):
        await service.admin_refund(uuid.uuid4(), admin=admin)


@pytest.mark.asyncio
async def test_cancel_unpaid_only():
    session = AsyncMock()
    service = CocreationPaymentService(session)
    purchase = SimpleNamespace(
        buyer_id=uuid.uuid4(),
        payment_status=SoftwarePaymentStatus.COMPLETED,
    )
    service._purchase_repo = AsyncMock()
    service._purchase_repo.get_by_id_for_update = AsyncMock(return_value=purchase)
    buyer = MagicMock()
    buyer.id = purchase.buyer_id
    with pytest.raises(AppException, match="unpaid"):
        await service.cancel_unpaid_purchase(uuid.uuid4(), buyer=buyer)
