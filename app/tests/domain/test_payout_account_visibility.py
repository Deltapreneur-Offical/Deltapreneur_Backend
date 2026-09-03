"""Payout account visibility contracts for seller and admin APIs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.service.domain.domain_marketplace_transaction_service import (
    DomainMarketplaceTransactionService,
)
from app.service.payout.seller_payout_profile_service import SellerPayoutProfileService
from app.utils.transfer_enums import (
    MarketplaceEscrowStatus,
    MarketplaceTransferStatus,
    PayoutMethod,
    SellerKycStatus,
    TransferDisputeStatus,
)


class _EmptyScalarResult:
    def all(self):
        return []


class _EmptyExecuteResult:
    def scalars(self):
        return _EmptyScalarResult()


class _FakeSession:
    async def execute(self, _query):
        return _EmptyExecuteResult()


class _FakeProfileRepo:
    def __init__(self, profile):
        self._profile = profile

    async def get_by_user_id(self, _user_id):
        return self._profile


def _profile(account_number: str = "123456789"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        payout_method=PayoutMethod.BANK_ACCOUNT,
        account_holder_name="Rohit Seller",
        bank_name="HDFC Bank",
        account_number=account_number,
        account_number_last4=account_number[-4:],
        bank_account_number_encrypted=None,
        bank_ifsc="HDFC0001234",
        upi_id_encrypted=None,
        kyc_status=SellerKycStatus.SUBMITTED,
        beneficiary_validated_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _transaction(seller_id: uuid.UUID):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(),
        domain_listing_id=uuid.uuid4(),
        domain_fqdn="example.com",
        buyer=None,
        seller=None,
        buyer_id=uuid.uuid4(),
        seller_id=seller_id,
        gross_amount_inr=1000.0,
        platform_fee_inr=150.0,
        seller_payout_inr=850.0,
        razorpay_order_id="order_test_123",
        razorpay_payment_id="pay_test_123",
        escrow_status=MarketplaceEscrowStatus.HELD,
        transfer_status=MarketplaceTransferStatus.TRANSFER_COMPLETED,
        transfer_method=None,
        assistance_requested_at=None,
        seller_registrar_name=None,
        buyer_target_registrar=None,
        seller_deadline_at=now,
        buyer_deadline_at=None,
        auth_code_submitted_at=None,
        auth_code_viewed_at=None,
        transfer_started_at=None,
        transfer_confirmed_at=None,
        transfer_verified_by=None,
        whois_supports_transfer=None,
        whois_registrar_snapshot=None,
        dispute_status=TransferDisputeStatus.NONE,
        cobrother_request_id=None,
        admin_review_required_at=None,
        admin_review_reason=None,
        seller_paid_at=None,
        payout_approved_at=None,
        refund_completed_at=None,
        payout_profile_id=None,
        payout_approved_by_user_id=None,
        payout_snapshot_method=None,
        payout_snapshot_upi_id=None,
        payout_snapshot_account_holder=None,
        payout_snapshot_bank_name=None,
        payout_snapshot_account_number=None,
        payout_snapshot_ifsc=None,
        payout_snapshot_account_last4=None,
        payout_snapshot_captured_at=None,
        payout_snapshot_source=None,
        payout_reminder_sent_at=None,
        payout_reminder_count=0,
        auth_code_ciphertext=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_seller_api_masks_account_but_admin_transfer_api_returns_full_number():
    profile = _profile("123456789")

    seller_payload = SellerPayoutProfileService(_FakeSession())._serialize(profile)
    assert seller_payload["masked_account_number"] == "*****6789"
    assert seller_payload["maskedAccountNumber"] == "*****6789"
    assert seller_payload["has_account_number"] is True
    assert "account_number" not in seller_payload
    assert "accountNumber" not in seller_payload

    service = DomainMarketplaceTransactionService.__new__(DomainMarketplaceTransactionService)
    service._session = _FakeSession()
    service._profiles = _FakeProfileRepo(profile)

    admin_payload = await service.serialize(
        _transaction(profile.user_id),
        include_payout_profile=True,
    )
    assert admin_payload["razorpayOrderId"] == "order_test_123"
    payout_profile = admin_payload["sellerPayoutProfile"]

    assert payout_profile["accountNumber"] == "123456789"
    assert payout_profile["account_number"] == "123456789"
    assert payout_profile["account_number_last4"] == "6789"
    assert payout_profile["fullAccountNumber"] == "123456789"
    assert payout_profile["bankAccountNumber"] == "123456789"
    assert payout_profile["maskedAccountNumber"] == "*****6789"
    assert "Account number not yet provided" not in payout_profile.values()
