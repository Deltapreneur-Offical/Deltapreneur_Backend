"""Service-level unit tests for domain transfer state machine."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AppException
from app.service.domain.domain_transfer_buyer_service import DomainTransferBuyerService
from app.service.domain.domain_transfer_escrow_service import DomainTransferEscrowService
from app.service.domain.domain_transfer_ops_service import DomainTransferOpsService
from app.service.domain.domain_transfer_seller_service import DomainTransferSellerService
from app.utils.transfer_enums import (
    MarketplaceEscrowStatus,
    MarketplaceTransferStatus,
    TransferVerifiedBy,
)


def _tx(**overrides):
    base = {
        "id": uuid.uuid4(),
        "buyer_id": uuid.uuid4(),
        "seller_id": uuid.uuid4(),
        "domain_listing_id": uuid.uuid4(),
        "domain_fqdn": "example.com",
        "auth_code_ciphertext": "cipher",
        "auth_code_key_version": 1,
        "transfer_status": MarketplaceTransferStatus.AUTH_CODE_RECEIVED,
        "gross_amount_inr": 1000.0,
        "razorpay_payment_id": "pay_test",
        "seller_deadline_at": datetime.now(timezone.utc) + timedelta(hours=12),
    }
    base.update(overrides)
    tx = MagicMock()
    for k, v in base.items():
        setattr(tx, k, v)
    return tx


@pytest.mark.asyncio
async def test_seller_submit_rejects_wrong_status():
    session = AsyncMock()
    session.commit = AsyncMock()
    service = DomainTransferSellerService(session)
    tx = _tx(transfer_status=MarketplaceTransferStatus.SELLER_PAID)
    service._repo.get_by_id_for_update = AsyncMock(return_value=tx)
    seller = MagicMock(id=tx.seller_id)

    with pytest.raises(AppException) as exc:
        await service.submit_auth_code(
            tx.id,
            seller=seller,
            registrar_name="GoDaddy",
            auth_code="AUTH1234",
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_buyer_confirm_moves_to_payout_pending():
    session = AsyncMock()
    session.commit = AsyncMock()
    service = DomainTransferBuyerService(session)
    tx = _tx(transfer_status=MarketplaceTransferStatus.TRANSFER_IN_PROGRESS)
    service._repo.get_by_id_for_update = AsyncMock(return_value=tx)
    service._repo.save = AsyncMock(side_effect=lambda x: x)
    service._events.log = AsyncMock()
    buyer = MagicMock(id=tx.buyer_id)

    await service.confirm_transfer(tx.id, buyer=buyer)

    assert tx.transfer_status == MarketplaceTransferStatus.PAYOUT_PENDING
    assert tx.transfer_verified_by == TransferVerifiedBy.BUYER
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_ops_escalates_seller_deadline_to_admin_review():
    session = AsyncMock()
    session.commit = AsyncMock()
    service = DomainTransferOpsService(session)
    overdue = _tx(transfer_status=MarketplaceTransferStatus.AWAITING_AUTH_CODE)
    overdue.seller = None
    overdue.email_admin_review_sent = False

    service._repo.list_seller_deadline_candidates = AsyncMock(return_value=[overdue])
    service._repo.list_reminder_candidates = AsyncMock(return_value=[])
    service._repo.save = AsyncMock(side_effect=lambda x: x)
    service._events.log = AsyncMock()
    service._notify.on_admin_review_required = AsyncMock()
    service._whois.poll_in_progress = AsyncMock(return_value=0)

    stats = await service.run_tick()

    assert stats["timeouts"] == 1
    assert overdue.transfer_status == MarketplaceTransferStatus.ADMIN_REVIEW_REQUIRED
    assert overdue.admin_review_reason == "SELLER_AUTH_CODE_TIMEOUT"


@pytest.mark.asyncio
async def test_escrow_refund_calls_razorpay():
    session = AsyncMock()
    session.commit = AsyncMock()
    service = DomainTransferEscrowService(session)
    tx = _tx(transfer_status=MarketplaceTransferStatus.ADMIN_REVIEW_REQUIRED)
    tx.escrow_status = MarketplaceEscrowStatus.HELD
    service._repo.get_by_id_for_update = AsyncMock(return_value=tx)
    service._repo.save = AsyncMock(side_effect=lambda x: x)
    service._listings.get_by_id_for_update = AsyncMock(return_value=MagicMock())
    service._listings.save = AsyncMock()
    service._events.log = AsyncMock()
    service._notify.on_refund = AsyncMock()
    admin = MagicMock(id=uuid.uuid4())

    with patch(
        "app.service.domain.domain_transfer_escrow_service.rzp.refund_payment",
        return_value={"id": "rfnd_test"},
    ) as mock_refund:
        result = await service.refund(tx.id, admin=admin)

    assert result["success"] is True
    assert result["refundId"] == "rfnd_test"
    assert tx.transfer_status == MarketplaceTransferStatus.REFUNDED
    # Verify GST-inclusive amount was passed (1000 * 1.18 = 1180)
    mock_refund.assert_called_once_with("pay_test", 1180.0)


@pytest.mark.asyncio
async def test_escrow_refund_uses_gst_inclusive_amount():
    """Refund must use the full buyer-paid amount including GST, not just
    the pre-GST gross_amount_inr stored in the transaction."""
    session = AsyncMock()
    session.commit = AsyncMock()
    service = DomainTransferEscrowService(session)
    # gross_amount_inr=5000 means buyer paid 5000*1.18=5900
    tx = _tx(
        transfer_status=MarketplaceTransferStatus.ADMIN_REVIEW_REQUIRED,
        gross_amount_inr=5000.0,
    )
    tx.escrow_status = MarketplaceEscrowStatus.HELD
    service._repo.get_by_id_for_update = AsyncMock(return_value=tx)
    service._repo.save = AsyncMock(side_effect=lambda x: x)
    service._listings.get_by_id_for_update = AsyncMock(return_value=MagicMock())
    service._listings.save = AsyncMock()
    service._events.log = AsyncMock()
    service._notify.on_refund = AsyncMock()
    admin = MagicMock(id=uuid.uuid4())

    with patch(
        "app.service.domain.domain_transfer_escrow_service.rzp.refund_payment",
        return_value={"id": "rfnd_gst"},
    ) as mock_refund:
        result = await service.refund(tx.id, admin=admin)

    assert result["success"] is True
    # 5000 * 1.18 = 5900 — the GST-inclusive amount the buyer actually paid
    mock_refund.assert_called_once_with("pay_test", 5900.0)


@pytest.mark.asyncio
async def test_escrow_refund_already_refunded_is_idempotent():
    """Double-clicking Refund on an already-refunded transaction should
    return success without calling Razorpay again."""
    session = AsyncMock()
    session.commit = AsyncMock()
    service = DomainTransferEscrowService(session)
    tx = _tx(transfer_status=MarketplaceTransferStatus.REFUNDED)
    tx.escrow_status = MarketplaceEscrowStatus.REFUNDED
    tx.razorpay_refund_id = "rfnd_existing"
    service._repo.get_by_id_for_update = AsyncMock(return_value=tx)
    admin = MagicMock(id=uuid.uuid4())

    result = await service.refund(tx.id, admin=admin)

    assert result["success"] is True
    assert result["refundId"] == "rfnd_existing"


@pytest.mark.asyncio
async def test_escrow_refund_rejects_no_payment():
    """Transaction with no razorpay_payment_id cannot be refunded."""
    session = AsyncMock()
    session.commit = AsyncMock()
    service = DomainTransferEscrowService(session)
    tx = _tx(
        transfer_status=MarketplaceTransferStatus.ADMIN_REVIEW_REQUIRED,
        razorpay_payment_id=None,
    )
    tx.escrow_status = MarketplaceEscrowStatus.HELD
    service._repo.get_by_id_for_update = AsyncMock(return_value=tx)
    admin = MagicMock(id=uuid.uuid4())

    with pytest.raises(AppException) as exc:
        await service.refund(tx.id, admin=admin)
    assert exc.value.status_code == 400
    assert "No payment" in exc.value.message


@pytest.mark.asyncio
async def test_escrow_refund_rejects_released_escrow():
    """Cannot refund after escrow has been released (seller already paid)."""
    session = AsyncMock()
    session.commit = AsyncMock()
    service = DomainTransferEscrowService(session)
    tx = _tx(transfer_status=MarketplaceTransferStatus.PAYOUT_RELEASED)
    tx.escrow_status = MarketplaceEscrowStatus.RELEASED
    service._repo.get_by_id_for_update = AsyncMock(return_value=tx)
    admin = MagicMock(id=uuid.uuid4())

    with pytest.raises(AppException) as exc:
        await service.refund(tx.id, admin=admin)
    assert exc.value.status_code == 409
    assert "released" in exc.value.message.lower()


@pytest.mark.asyncio
async def test_escrow_refund_handles_razorpay_failure():
    """Razorpay refund errors should be caught and wrapped as 502, not 500."""
    session = AsyncMock()
    session.commit = AsyncMock()
    service = DomainTransferEscrowService(session)
    tx = _tx(transfer_status=MarketplaceTransferStatus.ADMIN_REVIEW_REQUIRED)
    tx.escrow_status = MarketplaceEscrowStatus.HELD
    service._repo.get_by_id_for_update = AsyncMock(return_value=tx)
    admin = MagicMock(id=uuid.uuid4())

    with patch(
        "app.service.domain.domain_transfer_escrow_service.rzp.refund_payment",
        side_effect=RuntimeError("Razorpay connection failed"),
    ):
        with pytest.raises(AppException) as exc:
            await service.refund(tx.id, admin=admin)
    assert exc.value.status_code == 502
    assert "Razorpay refund failed" in exc.value.message


@pytest.mark.asyncio
async def test_escrow_refund_rejects_nonexistent_transaction():
    """Refunding a nonexistent transaction returns 404."""
    session = AsyncMock()
    session.commit = AsyncMock()
    service = DomainTransferEscrowService(session)
    service._repo.get_by_id_for_update = AsyncMock(return_value=None)
    admin = MagicMock(id=uuid.uuid4())

    with pytest.raises(AppException) as exc:
        await service.refund(uuid.uuid4(), admin=admin)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_escrow_refund_rejects_terminal_transfer_status():
    """Cannot refund a transaction with terminal transfer status (e.g. COMPLETED)."""
    session = AsyncMock()
    session.commit = AsyncMock()
    service = DomainTransferEscrowService(session)
    tx = _tx(transfer_status=MarketplaceTransferStatus.COMPLETED)
    tx.escrow_status = MarketplaceEscrowStatus.HELD
    service._repo.get_by_id_for_update = AsyncMock(return_value=tx)
    admin = MagicMock(id=uuid.uuid4())

    with pytest.raises(AppException) as exc:
        await service.refund(tx.id, admin=admin)
    assert exc.value.status_code == 409
    assert "terminal" in exc.value.message.lower()


@pytest.mark.asyncio
async def test_escrow_refund_idempotent_on_transfer_refunded_status():
    """If transfer_status is REFUNDED but escrow_status is not, refund is idempotent."""
    session = AsyncMock()
    session.commit = AsyncMock()
    service = DomainTransferEscrowService(session)
    tx = _tx(transfer_status=MarketplaceTransferStatus.REFUNDED)
    tx.escrow_status = MarketplaceEscrowStatus.HELD
    tx.razorpay_refund_id = "rfnd_transfer_ref"
    service._repo.get_by_id_for_update = AsyncMock(return_value=tx)
    admin = MagicMock(id=uuid.uuid4())

    result = await service.refund(tx.id, admin=admin)
    assert result["success"] is True
    assert result["refundId"] == "rfnd_transfer_ref"


@pytest.mark.asyncio
async def test_force_complete_requires_reason():
    """Force Complete without a reason must be rejected."""
    session = AsyncMock()
    session.commit = AsyncMock()
    service = DomainTransferEscrowService(session)
    tx = _tx(transfer_status=MarketplaceTransferStatus.TRANSFER_IN_PROGRESS)
    service._repo.get_by_id_for_update = AsyncMock(return_value=tx)
    service._repo.save = AsyncMock(side_effect=lambda x: x)
    admin = MagicMock(id=uuid.uuid4())

    with pytest.raises(AppException) as exc:
        await service.force_complete(tx.id, admin=admin)
    assert exc.value.status_code == 400
    assert "reason" in exc.value.message.lower()


@pytest.mark.asyncio
async def test_force_complete_with_reason_succeeds():
    """Force Complete with a valid reason should succeed."""
    session = AsyncMock()
    session.commit = AsyncMock()
    service = DomainTransferEscrowService(session)
    tx = _tx(transfer_status=MarketplaceTransferStatus.TRANSFER_IN_PROGRESS)
    service._repo.get_by_id_for_update = AsyncMock(return_value=tx)
    service._repo.save = AsyncMock(side_effect=lambda x: x)
    service._events.log = AsyncMock()
    admin = MagicMock(id=uuid.uuid4())

    result = await service.force_complete(tx.id, admin=admin, reason="Verified via external registrar")
    assert result["success"] is True
    assert tx.transfer_status == MarketplaceTransferStatus.PAYOUT_PENDING
    assert tx.transfer_verified_by == TransferVerifiedBy.ADMIN
    # Verify reason was recorded in audit event
    calls = service._events.log.call_args_list
    confirm_call = calls[0]
    assert confirm_call[1]["payload"]["forced"] is True
    assert confirm_call[1]["payload"]["reason"] == "Verified via external registrar"
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_force_complete_rejects_closed_transaction():
    """Force Complete on a closed transaction should fail."""
    session = AsyncMock()
    session.commit = AsyncMock()
    service = DomainTransferEscrowService(session)
    tx = _tx(transfer_status=MarketplaceTransferStatus.REFUNDED)
    service._repo.get_by_id_for_update = AsyncMock(return_value=tx)
    admin = MagicMock(id=uuid.uuid4())

    with pytest.raises(AppException) as exc:
        await service.force_complete(tx.id, admin=admin, reason="test")
    assert exc.value.status_code == 409
