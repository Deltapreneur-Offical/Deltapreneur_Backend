"""Razorpay Orders API + signature verification."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any, Optional

import razorpay
from razorpay.errors import BadRequestError
from requests.exceptions import ConnectionError, Timeout

from app.core.config import settings

logger = logging.getLogger(__name__)


def _key_id() -> str:
    return settings.resolved_razorpay_key_id()


def _key_secret() -> str:
    return settings.resolved_razorpay_key_secret()


def _webhook_secret() -> str:
    return settings.resolved_razorpay_webhook_secret()


def is_configured() -> bool:
    return bool(_key_id() and _key_secret())


def get_key_id() -> str:
    return _key_id()


def is_test_mode() -> bool:
    kid = _key_id()
    return kid.startswith("rzp_test_")


def get_environment() -> Optional[str]:
    kid = _key_id()
    if kid.startswith("rzp_test_"):
        return "TEST"
    if kid.startswith("rzp_live_"):
        return "LIVE"
    return None


_PAYMENT_ENV_CACHE: dict[str, tuple[float, Optional[str]]] = {}
_PAYMENT_ENV_CACHE_TTL_SECONDS = 600.0


def resolve_payment_environment(payment_id: str) -> Optional[str]:
    pid = str(payment_id or "").strip()
    if not pid:
        return None
    now = time.monotonic()
    cached = _PAYMENT_ENV_CACHE.get(pid)
    if cached and (now - cached[0]) < _PAYMENT_ENV_CACHE_TTL_SECONDS:
        return cached[1]
    current = get_environment()
    if current is None or not is_configured():
        return None
    try:
        fetch_payment(pid)
        resolved: Optional[str] = current
    except BadRequestError:
        resolved = "TEST" if current == "LIVE" else "LIVE"
    except Exception:
        resolved = None
    _PAYMENT_ENV_CACHE[pid] = (time.monotonic(), resolved)
    return resolved


_TEST_MODE_MAX_ORDER_INR = 100_000.0


def _allow_dev_payment_bypass() -> bool:
    """Mock/test signature shortcuts are never allowed with live keys or in production."""
    if (settings.ENVIRONMENT or "").strip().lower() == "production":
        return False
    return is_test_mode()


def _normalize_receipt(receipt: str) -> str:
    cleaned = (receipt or "order").strip()
    return cleaned[:40] if len(cleaned) > 40 else cleaned


_ZERO_DECIMAL_CURRENCIES = {
    "BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW",
    "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF",
}

_THREE_DECIMAL_CURRENCIES = {"BHD", "JOD", "KWD", "OMR", "TND"}


def _to_smallest_unit(amount: float, currency: str) -> int:
    code = currency.upper()
    if code in _ZERO_DECIMAL_CURRENCIES:
        return int(round(amount))
    if code in _THREE_DECIMAL_CURRENCIES:
        return int(round(amount * 1000))
    return int(round(amount * 100))


def create_order(
    *,
    amount_inr: float,
    receipt: str,
    notes: Optional[dict[str, str]] = None,
    currency: str = "INR",
) -> dict[str, Any]:
    if not is_configured():
        raise RuntimeError("Razorpay is not configured (RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET).")

    if amount_inr <= 0:
        raise ValueError("Order amount must be greater than zero.")

    if is_test_mode() and currency.upper() == "INR" and amount_inr > _TEST_MODE_MAX_ORDER_INR:
        raise ValueError(
            f"Amount INR {amount_inr:,.2f} exceeds Razorpay test-mode limit "
            f"(INR {_TEST_MODE_MAX_ORDER_INR:,.0f}). Use live keys for larger payments, "
            "or continue via Add to Cart / assisted purchase."
        )

    client = razorpay.Client(auth=(_key_id(), _key_secret()))
    payload: dict[str, Any] = {
        "amount": _to_smallest_unit(amount_inr, currency),
        "currency": currency.upper(),
        "receipt": _normalize_receipt(receipt),
    }
    if notes:
        payload["notes"] = notes
    try:
        order = client.order.create(data=payload)
    except ConnectionError as exc:
        raise ConnectionError(
            f"Unable to reach Razorpay (connection error): {exc}"
        ) from exc
    except Timeout as exc:
        raise Timeout(
            f"Razorpay order creation timed out: {exc}"
        ) from exc
    except Exception as exc:
        msg = str(exc)
        if "maximum amount" in msg.lower() or "amount exceeds" in msg.lower():
            raise ValueError(
                "This purchase amount exceeds the payment gateway limit for instant checkout. "
                "Please use Add to Cart or contact support for assisted purchase."
            ) from exc

        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        body = ""
        if response is not None:
            try:
                body = response.text or ""
            except Exception:
                body = "<unreadable>"
        error_msg = (
            f"Razorpay order creation failed [status={status_code}]: {msg}. "
            f"Response body: {body[:1000]}"
        )
        if "currency" in msg.lower() or "unsupported currency" in body.lower():
            raise ValueError(
                f"Currency {currency.upper()} is not supported by the payment gateway."
            ) from exc
        raise RuntimeError(error_msg) from exc
    return dict(order)


def verify_payment_signature(
    order_id: str,
    payment_id: str,
    signature: str,
) -> bool:
    if _allow_dev_payment_bypass() and (
        not signature or signature.startswith("mock_")
    ):
        return True
    secret = _key_secret()
    if not secret:
        return False
    payload = f"{order_id}|{payment_id}"
    expected = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(body: bytes, signature_header: str) -> bool:
    secret = _webhook_secret()
    if not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def fetch_payment(payment_id: str) -> dict[str, Any]:
    if not is_configured():
        raise RuntimeError("Razorpay is not configured.")
    client = razorpay.Client(auth=(_key_id(), _key_secret()))
    return dict(client.payment.fetch(payment_id))


def fetch_order(order_id: str) -> dict[str, Any]:
    if not is_configured():
        raise RuntimeError("Razorpay is not configured.")
    client = razorpay.Client(auth=(_key_id(), _key_secret()))
    return dict(client.order.fetch(order_id))


def assert_captured_payment_for_order(
    *,
    payment_id: str,
    order_id: str,
    expected_buyer_id: str | None = None,
) -> dict[str, Any]:
    if _allow_dev_payment_bypass() and (
        not payment_id or str(payment_id).startswith("mock_")
    ):
        return {"id": payment_id, "order_id": order_id, "status": "captured", "mock": True}

    payment = fetch_payment(payment_id)
    status = str(payment.get("status") or "").lower()
    if status not in {"captured", "authorized"}:
        raise ValueError(f"Payment status is not captured ({status or 'unknown'}).")
    paid_order = str(payment.get("order_id") or "")
    if paid_order != order_id:
        raise ValueError("Payment does not match Razorpay order.")

    order = fetch_order(order_id)
    pay_amount = payment.get("amount")
    order_amount = order.get("amount")
    if pay_amount is not None and order_amount is not None and int(pay_amount) != int(order_amount):
        raise ValueError("Payment amount does not match Razorpay order.")
    pay_currency = str(payment.get("currency") or "").upper()
    order_currency = str(order.get("currency") or "").upper()
    if pay_currency and order_currency and pay_currency != order_currency:
        raise ValueError("Payment currency does not match Razorpay order.")

    if expected_buyer_id:
        notes = order.get("notes") or {}
        note_buyer = str(notes.get("buyerId") or notes.get("buyer_id") or "").strip()
        if not note_buyer:
            raise ValueError("Payment order is missing buyer binding.")
        if note_buyer != str(expected_buyer_id):
            raise ValueError("Payment order does not belong to this buyer.")

    return payment


# ---------------------------------------------------------------------------
# Refund
# ---------------------------------------------------------------------------

class AlreadyFullyRefunded(Exception):
    """Raised when a Razorpay payment is already fully refunded.

    Carries the real Razorpay refund information so the caller can
    present it without generating any fake IDs.
    """

    def __init__(
        self,
        *,
        payment_id: str,
        refund_id: str | None,
        amount_refunded_paise: int,
        captured_amount_paise: int,
    ) -> None:
        self.payment_id = payment_id
        self.refund_id = refund_id
        self.amount_refunded_paise = amount_refunded_paise
        self.captured_amount_paise = captured_amount_paise
        msg = (
            f"Payment {payment_id} is already fully refunded on Razorpay. "
            f"Real refund ID: {refund_id or 'unknown'}"
        )
        super().__init__(msg)


def _fetch_existing_refund_id(
    client_obj: razorpay.Client, payment_id: str
) -> str | None:
    """Fetch the real Razorpay refund ID for an already-refunded payment.

    Returns the most recent refund ID, or None if no refund records
    are found.
    """
    try:
        result = client_obj.payment.fetch_multiple_refund(
            payment_id, {"count": 1}
        )
        items = result.get("items") or []
        if items:
            return items[0].get("id")
    except Exception:
        pass
    return None


def refund_payment(
    payment_id: str,
    amount_inr: float,
    currency: str = "INR",
) -> dict[str, Any]:
    """Refund a payment via the REAL Razorpay Refund API.

    This function NEVER generates fake refund IDs.  Every refund ID
    comes directly from Razorpay's API response.

    If the payment is already fully refunded on Razorpay, raises
    ``AlreadyFullyRefunded`` with the real Razorpay refund ID — no
    new refund is attempted.

    Raises:
        AlreadyFullyRefunded: payment already fully refunded on Razorpay.
        ValueError: business-logic errors (wrong status, amount exceeds
            refundable, etc.).
        RuntimeError: network/API/configuration errors.
    """
    if not is_configured():
        raise RuntimeError("Razorpay is not configured.")

    client_obj = razorpay.Client(auth=(_key_id(), _key_secret()))

    # --- Fetch the actual payment from Razorpay ---
    try:
        payment = client_obj.payment.fetch(payment_id)
    except Exception as exc:
        raise RuntimeError(
            f"Could not fetch payment {payment_id} from Razorpay: {exc}"
        ) from exc

    actual_currency = (payment.get("currency") or currency).upper()
    actual_amount = int(payment.get("amount") or 0)
    payment_status = str(payment.get("status") or "").lower()
    already_refunded = int(payment.get("amount_refunded") or 0)

    logger.info(
        "razorpay.refund.fetch payment=%s status=%s amount=%s refunded=%s",
        payment_id, payment_status, actual_amount, already_refunded,
    )

    # --- If already fully refunded, fetch the real Razorpay refund ID ---
    if payment_status == "refunded" or (
        payment_status in ("captured", "authorized")
        and already_refunded >= actual_amount
        and actual_amount > 0
    ):
        existing_refund_id = _fetch_existing_refund_id(client_obj, payment_id)
        raise AlreadyFullyRefunded(
            payment_id=payment_id,
            refund_id=existing_refund_id,
            amount_refunded_paise=already_refunded,
            captured_amount_paise=actual_amount,
        )

    # --- Validate payment status ---
    if payment_status not in ("captured", "authorized"):
        raise ValueError(
            f"Cannot refund payment in '{payment_status}' status. "
            f"Only captured or authorized payments can be refunded."
        )

    # --- Determine the refund amount ---
    refundable_paise = max(actual_amount - already_refunded, 0)
    requested_paise = _to_smallest_unit(amount_inr, currency.upper())
    refund_amount = min(requested_paise, refundable_paise)

    if refund_amount <= 0:
        raise ValueError(
            f"Nothing left to refund. Captured: {actual_amount} paise, "
            f"already refunded: {already_refunded} paise."
        )

    logger.info(
        "razorpay.refund.attempt payment=%s amount_paise=%s refundable_paise=%s",
        payment_id, refund_amount, refundable_paise,
    )

    # --- Call the REAL Razorpay Refund API ---
    try:
        refund = client_obj.payment.refund(payment_id, {"amount": refund_amount})
    except BadRequestError as exc:
        raise ValueError(
            f"Razorpay rejected refund: {exc}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"Razorpay refund API call failed: {exc}"
        ) from exc

    # --- Verify the response contains a real Razorpay refund ID ---
    refund_id = refund.get("id")
    if not refund_id or not str(refund_id).startswith("rfnd_"):
        raise RuntimeError(
            f"Razorpay returned unexpected refund response: {refund}"
        )

    logger.info(
        "razorpay.refund.success payment=%s refund_id=%s amount=%s status=%s",
        payment_id, refund_id, refund.get("amount"), refund.get("status"),
    )

    return dict(refund)


def fetch_recent_payments(count: int = 50) -> list[dict[str, Any]]:
    """Fetch recent payments from Razorpay API."""
    if not is_configured():
        return []
    try:
        client = razorpay.Client(auth=(_key_id(), _key_secret()))
        res = client.payment.all({"count": count})
        items = res.get("items") or []
        return [dict(i) for i in items]
    except Exception:
        return []
