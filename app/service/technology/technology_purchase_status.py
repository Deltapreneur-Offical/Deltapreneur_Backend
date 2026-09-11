"""Customer-facing and admin-queue status for paid technology subscriptions.

Provisioning failure must never be presented as a payment failure, and a
missing provider order ID must never hide a captured purchase from recovery.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.core.config import settings


PAID_PAYMENT_STATUSES = {"CAPTURED", "COMPLETED", "PAID", "SUCCESS"}
FAILED_PAYMENT_STATUSES = {"FAILED", "CANCELLED", "REFUNDED"}
RETRYABLE_PROVISIONING_STATUSES = (
    "PENDING",
    "PROVISIONING_FAILED",
    "PAYMENT_CAPTURED",
    "PROVISIONING",
)
ACTIVE_PROVISIONING_STATUSES = {"ACTIVE"}


def _upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _max_retries() -> int:
    return max(1, int(getattr(settings, "TECH_SUBSCRIPTION_MAX_RETRIES", 5) or 5))


def is_paid_payment(payment_status: Any) -> bool:
    return _upper(payment_status) in PAID_PAYMENT_STATUSES


def is_failed_provisioning_queue_item(sub: Any, *, max_retries: int | None = None) -> bool:
    """True when a paid technology subscription still needs provider activation.

    A NULL provider_order_id is a reason to *include* the row, never exclude it.
    """
    del max_retries  # retry policy affects labels, not queue membership
    if bool(getattr(sub, "is_deleted", False)):
        return False
    if not is_paid_payment(getattr(sub, "payment_status", None)):
        return False
    return _upper(getattr(sub, "status", None)) in RETRYABLE_PROVISIONING_STATUSES


def customer_activation_view(sub: Any, *, max_retries: int | None = None) -> dict[str, Any]:
    """Map payment + provisioning state to My Purchases fields.

    Labels are derived only from payment_status / status / needs_review /
    provision_attempts — never from product name or slug.
    """
    payment = _upper(getattr(sub, "payment_status", None))
    status = _upper(getattr(sub, "status", None))
    needs_review = bool(getattr(sub, "needs_review", False))
    attempts = int(getattr(sub, "provision_attempts", 0) or 0)
    limit = _max_retries() if max_retries is None else max(1, int(max_retries))

    if payment in FAILED_PAYMENT_STATUSES:
        return {
            "paymentStatus": "FAILED" if payment == "FAILED" else payment,
            "activationStatus": "PAYMENT_FAILED",
            "activationStatusLabel": "Payment Failed",
            "completionStatus": "PENDING",
            "provisioningStatus": status or None,
        }

    payment_out = "COMPLETED" if is_paid_payment(payment) else (payment or "PENDING")

    if status in ACTIVE_PROVISIONING_STATUSES:
        return {
            "paymentStatus": payment_out,
            "activationStatus": "ACTIVE",
            "activationStatusLabel": "Active",
            "completionStatus": "ACTIVE",
            "provisioningStatus": status,
        }

    terminal = bool(needs_review) or (status == "PROVISIONING_FAILED" and attempts >= limit)
    if is_paid_payment(payment) and terminal:
        return {
            "paymentStatus": payment_out,
            "activationStatus": "ACTIVATION_ISSUE",
            "activationStatusLabel": "Activation Issue",
            "completionStatus": "PENDING",
            "provisioningStatus": status,
        }

    if is_paid_payment(payment):
        return {
            "paymentStatus": payment_out,
            "activationStatus": "PENDING_ACTIVATION",
            "activationStatusLabel": "Pending Activation",
            "completionStatus": "PENDING",
            "provisioningStatus": status,
        }

    return {
        "paymentStatus": payment_out,
        "activationStatus": "PAYMENT_PENDING",
        "activationStatusLabel": "Payment Pending",
        "completionStatus": "PENDING",
        "provisioningStatus": status or None,
    }


def serialize_failed_provisioning_item(
    sub: Any,
    *,
    user_email: str | None = None,
    max_retries: int | None = None,
) -> dict[str, Any]:
    """Admin Failed Provisioning card payload. Never requires a provider ID."""
    limit = _max_retries() if max_retries is None else max(1, int(max_retries))
    attempts = int(getattr(sub, "provision_attempts", 0) or 0)
    needs_review = bool(getattr(sub, "needs_review", False))
    terminal = needs_review or attempts >= limit
    attempted = (
        getattr(sub, "last_provision_attempt_at", None)
        or getattr(sub, "created_at", None)
    )
    next_retry = getattr(sub, "next_retry_at", None)
    return {
        "id": str(getattr(sub, "id")),
        "user_id": getattr(sub, "user_id", None),
        "user_email": user_email or getattr(sub, "user_id", None),
        "service_slug": getattr(sub, "service_slug", None),
        "service_name": getattr(sub, "service_name", None),
        "plan_code": getattr(sub, "plan_code", None),
        "billing_cycle": getattr(sub, "billing_cycle", None),
        "payment_status": getattr(sub, "payment_status", None),
        "status": getattr(sub, "status", None),
        "provisioning_status": getattr(sub, "status", None),
        "error_reason": getattr(sub, "last_provider_error", None) or "",
        "retry_count": attempts,
        "provision_attempts": attempts,
        "max_retries": limit,
        "retry_eligible": is_paid_payment(getattr(sub, "payment_status", None)) and not terminal,
        "needs_review": needs_review,
        "provider_order_id": getattr(sub, "provider_order_id", None),
        "provider_subscription_id": getattr(sub, "provider_subscription_id", None),
        "attempted_at": _iso(attempted),
        "next_retry_at": _iso(next_retry),
        "razorpay_payment_id": getattr(sub, "razorpay_payment_id", None),
        "razorpay_order_id": getattr(sub, "razorpay_order_id", None),
    }


def retry_result_payload(sub: Any, outcome: str, *, error: Optional[str] = None) -> dict[str, Any]:
    success_outcomes = {
        "activated",
        "adopted",
        "pending",
        "email",
        "access",
        "already_active",
        "needs_input",
    }
    return {
        "success": outcome in success_outcomes,
        "outcome": outcome,
        "status": getattr(sub, "status", None),
        "payment_status": getattr(sub, "payment_status", None),
        "provider_order_id": getattr(sub, "provider_order_id", None),
        "provider_subscription_id": getattr(sub, "provider_subscription_id", None),
        "confirmation_sent": bool(getattr(sub, "confirmation_sent", False)),
        "access_email_sent": bool(getattr(sub, "access_email_sent", False)),
        "email_sent": bool(getattr(sub, "email_sent", False)),
        "provision_attempts": int(getattr(sub, "provision_attempts", 0) or 0),
        "needs_review": bool(getattr(sub, "needs_review", False)),
        "last_provider_error": getattr(sub, "last_provider_error", None),
        "error": error,
    }


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
