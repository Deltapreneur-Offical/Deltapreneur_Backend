"""Serialize domain marketplace transfer transactions."""

from __future__ import annotations

from typing import Any, Optional

from app.entity.domain.domain_marketplace_transaction_entity import DomainMarketplaceTransaction
from app.entity.user.app_user import AppUser


def _user_summary(user: Optional[AppUser]) -> Optional[dict[str, Any]]:
    if user is None:
        return None
    name = f"{user.firstname or ''} {user.lastname or ''}".strip()
    return {
        "id": str(user.id),
        "name": name or user.email,
        "email": user.email,
    }


def build_transfer_response(
    tx: DomainMarketplaceTransaction,
    *,
    include_auth_code: bool = False,
    auth_code_plain: Optional[str] = None,
) -> dict[str, Any]:
    # The buyer actually paid listing_price × 1.18 (with 18% GST).
    # gross_amount_inr stores the pre-GST listing price.
    gross = float(tx.gross_amount_inr or 0)
    gst_amount = round(gross * 0.18, 2) if gross > 0 else 0.0
    buyer_paid = round(gross * 1.18, 2) if gross > 0 else 0.0

    return {
        "id": str(tx.id),
        "domainListingId": str(tx.domain_listing_id),
        "domainFqdn": tx.domain_fqdn,
        "buyer": _user_summary(tx.buyer),
        "seller": _user_summary(tx.seller),
        "grossAmountInr": tx.gross_amount_inr,
        "gstAmountInr": gst_amount,
        "buyerPaidAmountInr": buyer_paid,
        "platformFeeInr": tx.platform_fee_inr,
        "sellerPayoutInr": tx.seller_payout_inr,
        "razorpayOrderId": getattr(tx, "razorpay_order_id", None),
        "razorpayPaymentId": getattr(tx, "razorpay_payment_id", None),
        "razorpayRefundId": getattr(tx, "razorpay_refund_id", None),
        "escrowStatus": tx.escrow_status.value,
        "transferStatus": tx.transfer_status.value,
        "transferMethod": tx.transfer_method.value if tx.transfer_method else None,
        "assistanceRequestedAt": (
            tx.assistance_requested_at.isoformat() if tx.assistance_requested_at else None
        ),
        "sellerRegistrarName": tx.seller_registrar_name,
        "buyerTargetRegistrar": tx.buyer_target_registrar,
        "sellerDeadlineAt": tx.seller_deadline_at.isoformat() if tx.seller_deadline_at else None,
        "buyerDeadlineAt": tx.buyer_deadline_at.isoformat() if tx.buyer_deadline_at else None,
        "authCodeSubmittedAt": (
            tx.auth_code_submitted_at.isoformat() if tx.auth_code_submitted_at else None
        ),
        "authCodeViewedAt": tx.auth_code_viewed_at.isoformat() if tx.auth_code_viewed_at else None,
        "transferStartedAt": tx.transfer_started_at.isoformat() if tx.transfer_started_at else None,
        "transferConfirmedAt": (
            tx.transfer_confirmed_at.isoformat() if tx.transfer_confirmed_at else None
        ),
        "transferVerifiedBy": tx.transfer_verified_by.value if tx.transfer_verified_by else None,
        "whoisSupportsTransfer": tx.whois_supports_transfer,
        "whoisRegistrarSnapshot": tx.whois_registrar_snapshot,
        "disputeStatus": tx.dispute_status.value,
        "cobrotherRequestId": str(tx.cobrother_request_id) if tx.cobrother_request_id else None,
        "adminReviewRequiredAt": (
            tx.admin_review_required_at.isoformat() if tx.admin_review_required_at else None
        ),
        "adminReviewReason": tx.admin_review_reason,
        "sellerPaidAt": tx.seller_paid_at.isoformat() if tx.seller_paid_at else None,
        "payoutApprovedAt": tx.payout_approved_at.isoformat() if tx.payout_approved_at else None,
        "refundCompletedAt": tx.refund_completed_at.isoformat() if tx.refund_completed_at else None,
        "hasAuthCode": bool(tx.auth_code_ciphertext),
        "authCode": auth_code_plain if include_auth_code else None,
        "createdAt": tx.created_at.isoformat() if tx.created_at else None,
        "updatedAt": tx.updated_at.isoformat() if tx.updated_at else None,
        # Historical seller payout snapshot (frozen at capture time)
        "sellerPayoutSnapshot": (
            {
                "preferredMethod": tx.payout_snapshot_method,
                "upiId": tx.payout_snapshot_upi_id,
                "accountHolderName": tx.payout_snapshot_account_holder,
                "bankName": tx.payout_snapshot_bank_name,
                "accountNumberLast4": tx.payout_snapshot_account_last4,
                "ifscCode": tx.payout_snapshot_ifsc,
                "snapshotCreatedAt": (
                    tx.payout_snapshot_captured_at.isoformat()
                    if tx.payout_snapshot_captured_at
                    else None
                ),
                "snapshotSource": tx.payout_snapshot_source,
            }
            if tx.payout_snapshot_captured_at
            else None
        ),
    }
