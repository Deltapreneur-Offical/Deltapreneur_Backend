"""Domain registration storefront enums."""

from __future__ import annotations

from enum import Enum


class RegistrationOrderStatus(str, Enum):
    CREATED = "CREATED"
    PAYMENT_COMPLETED = "PAYMENT_COMPLETED"
    REGISTRATION_PENDING = "REGISTRATION_PENDING"
    ACTIVE = "ACTIVE"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    PROVISION_FAILED = "PROVISION_FAILED"
    REFUNDED = "REFUNDED"
