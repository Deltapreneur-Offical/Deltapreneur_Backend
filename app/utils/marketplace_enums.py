"""Domain marketplace & cobrother workflow enums."""

from __future__ import annotations

from enum import Enum


class DomainCategory(str, Enum):
    BRANDABLE = "BRANDABLE"
    PREMIUM = "PREMIUM"
    GENERIC = "GENERIC"
    GEOGRAPHIC = "GEOGRAPHIC"
    NUMERIC = "NUMERIC"
    OTHER = "OTHER"


class DomainListingStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SOLD = "SOLD"
    PENDING = "PENDING"
    # Premium marketplace acquisition (> ₹5L): held while enquiry is managed.
    UNDER_REVIEW = "UNDER_REVIEW"


class PricingDemand(str, Enum):
    NEGOTIABLE = "NEGOTIABLE"
    FIXED = "FIXED"


class MarketplacePaymentStatus(str, Enum):
    CREATED = "CREATED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CONTACT_PENDING = "CONTACT_PENDING"
    REFUNDED = "REFUNDED"


class VerificationMethod(str, Enum):
    DNS = "DNS"
    META_TAG = "META_TAG"
    WHOIS_EMAIL = "WHOIS_EMAIL"


class SaleType(str, Enum):
    ONE_TIME = "ONE_TIME"
    AUCTION = "AUCTION"


class DomainListingVerificationStatus(str, Enum):
    """Admin verification workflow for domain listings (auction domains gated on VERIFIED)."""

    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    MORE_INFO_REQUESTED = "MORE_INFO_REQUESTED"


class DomainEnquiryStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    FORWARDED = "FORWARDED"


class CoBrotherRequestType(str, Enum):
    COVENTURE = "COVENTURE"
    DOMAIN = "DOMAIN"
    COCREATION = "COCREATION"
    DOMAIN_ENQUIRY = "DOMAIN_ENQUIRY"


class CoBrotherRequestStatus(str, Enum):
    PENDING = "PENDING"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_COMPLETED = "PAYMENT_COMPLETED"
    FORWARDED = "FORWARDED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
