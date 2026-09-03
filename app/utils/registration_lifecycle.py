"""User-facing lifecycle labels for domain registration orders."""

from __future__ import annotations

from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
from app.utils.registration_enums import RegistrationOrderStatus


def registration_lifecycle_status(order: DomainRegistrationOrder) -> str:
    """
    Stable storefront/admin status strings:
    payment_success | registration_pending | registration_confirmed | registration_failed
    """
    status = order.status
    if status == RegistrationOrderStatus.ACTIVE:
        return "registration_confirmed"
    if status == RegistrationOrderStatus.REGISTRATION_PENDING:
        return "registration_pending"
    if status == RegistrationOrderStatus.PROVISION_FAILED:
        return "registration_failed"
    if status == RegistrationOrderStatus.PAYMENT_FAILED:
        return "payment_failed"
    if status == RegistrationOrderStatus.PAYMENT_COMPLETED:
        return "payment_success"
    if status == RegistrationOrderStatus.CREATED:
        message = (order.provision_message or "").strip().lower()
        if "checkout cancelled before payment" in message or "pending registration order expired" in message:
            return "checkout_cancelled"
        return "awaiting_payment"
    if status == RegistrationOrderStatus.EXPIRED:
        return "checkout_cancelled"
    if status == RegistrationOrderStatus.FAILED:
        return "registration_failed"
    if status == RegistrationOrderStatus.REFUNDED:
        return "refunded"
    return status.value.lower()
