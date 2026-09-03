"""Transfer API response mapper."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.model.marketplace.transfer_mapper import build_transfer_response
from app.utils.transfer_enums import MarketplaceEscrowStatus, MarketplaceTransferStatus


def test_build_transfer_response_masks_auth_code():
    tx = SimpleNamespace(
        id=uuid.uuid4(),
        domain_listing_id=uuid.uuid4(),
        domain_fqdn="example.com",
        buyer=None,
        seller=None,
        gross_amount_inr=1000.0,
        platform_fee_inr=150.0,
        seller_payout_inr=850.0,
        escrow_status=MarketplaceEscrowStatus.HELD,
        transfer_status=MarketplaceTransferStatus.AWAITING_AUTH_CODE,
        transfer_method=None,
        assistance_requested_at=None,
        seller_registrar_name=None,
        buyer_target_registrar=None,
        seller_deadline_at=datetime.now(timezone.utc),
        buyer_deadline_at=None,
        auth_code_submitted_at=None,
        auth_code_viewed_at=None,
        transfer_started_at=None,
        transfer_confirmed_at=None,
        transfer_verified_by=None,
        whois_supports_transfer=None,
        whois_registrar_snapshot=None,
        dispute_status=SimpleNamespace(value="NONE"),
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
        auth_code_ciphertext="encrypted",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    out = build_transfer_response(tx)
    assert out["hasAuthCode"] is True
    assert out["authCode"] is None
