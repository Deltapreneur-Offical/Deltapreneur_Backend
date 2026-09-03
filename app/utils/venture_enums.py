"""Venture & co-venture domain enums."""

from __future__ import annotations

from enum import Enum


class Industry(str, Enum):
    TECH = "TECH"
    FINANCE = "FINANCE"
    HEALTHCARE = "HEALTHCARE"
    EDUCATION = "EDUCATION"
    FOOD_AND_BEVERAGE = "FOOD_AND_BEVERAGE"
    RETAIL = "RETAIL"
    REAL_ESTATE = "REAL_ESTATE"
    MEDIA = "MEDIA"
    MANUFACTURING = "MANUFACTURING"
    LOGISTICS = "LOGISTICS"
    AGRICULTURE = "AGRICULTURE"
    SAAS = "SAAS"
    ECOMMERCE = "ECOMMERCE"
    SERVICES = "SERVICES"
    AI_AUTOMATION = "AI_AUTOMATION"
    FINTECH = "FINTECH"
    OTHER = "OTHER"


class VentureType(str, Enum):
    FIFTY_FIFTY = "FIFTY_FIFTY"
    SIXTY_FORTY = "SIXTY_FORTY"
    SEVENTY_THIRTY = "SEVENTY_THIRTY"
    EIGHTY_TWENTY = "EIGHTY_TWENTY"
    NINETY_TEN = "NINETY_TEN"
    NEGOTIABLE = "NEGOTIABLE"


class VentureStage(str, Enum):
    IDEA = "IDEA"
    MVP = "MVP"
    REVENUE_GENERATING = "REVENUE_GENERATING"
    SCALING = "SCALING"


class VentureSaleType(str, Enum):
    REGULAR = "REGULAR"


class VentureListingMode(str, Enum):
    """Marketplace listing type: sale/acquisition vs partnership collaboration."""

    VENTURE = "VENTURE"
    CO_VENTURE = "CO_VENTURE"


class VentureListingStatus(str, Enum):
    """Post-approval lifecycle on the venture listing."""

    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    DEAL_FINALIZED = "DEAL_FINALIZED"
    PARTNERSHIP_FINALIZED = "PARTNERSHIP_FINALIZED"
    COMPLETED = "COMPLETED"


class CompanyType(str, Enum):
    PRIVATE_LIMITED = "PRIVATE_LIMITED"
    LLP = "LLP"
    PARTNERSHIP = "PARTNERSHIP"
    SOLE_PROPRIETORSHIP = "SOLE_PROPRIETORSHIP"
    PUBLIC_LIMITED = "PUBLIC_LIMITED"
    OTHER = "OTHER"


class VenturePitchStatus(str, Enum):
    PENDING = "PENDING"
    SHORTLISTED = "SHORTLISTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    DEAL_SELECTED = "DEAL_SELECTED"
    CANCELLED = "CANCELLED"


class VentureDealKind(str, Enum):
    VENTURE_SALE = "VENTURE_SALE"
    CO_VENTURE = "CO_VENTURE"


class VentureDealStatus(str, Enum):
    PENDING_ADMIN_APPROVAL = "PENDING_ADMIN_APPROVAL"
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAYMENT_HELD = "PAYMENT_HELD"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class VentureDealEventType(str, Enum):
    CREATED = "CREATED"
    PAYMENT_INITIATED = "PAYMENT_INITIATED"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
    ESCROW_RELEASED = "ESCROW_RELEASED"
    DEAL_COMPLETED = "DEAL_COMPLETED"
    DEAL_CANCELLED = "DEAL_CANCELLED"
    ADMIN_NOTE = "ADMIN_NOTE"


class VentureDealType(str, Enum):
    """Legacy listing subtype — superseded by ownership liquidation % on new listings."""

    FULL_ACQUISITION = "FULL_ACQUISITION"
    EQUITY_SALE = "EQUITY_SALE"


class VentureVerificationStatus(str, Enum):
    """Admin review status for optional listing verification requests."""

    NONE = "NONE"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class VentureAcquisitionFlow(str, Enum):
    """FULL_ACQUISITION sub-flow chosen by the seller at listing time.

    DIRECT_BUY: buyers purchase immediately at the listed price (buy-now checkout).
    SELLER_SELECTS: buyers submit acquisition offers; seller selects the buyer,
    which creates the deal and unlocks payment.
    """

    DIRECT_BUY = "DIRECT_BUY"
    SELLER_SELECTS = "SELLER_SELECTS"


class VentureAcquisitionApplicationStatus(str, Enum):
    PENDING = "PENDING"
    SHORTLISTED = "SHORTLISTED"
    SELLER_ACCEPTED = "SELLER_ACCEPTED"
    SELLER_REJECTED = "SELLER_REJECTED"
    DEAL_SELECTED = "DEAL_SELECTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class VentureAcquisitionApplicationSource(str, Enum):
    REGULAR_APPLY = "REGULAR_APPLY"
    AUCTION_WINNER = "AUCTION_WINNER"  # legacy rows from removed venture auctions


class CoVentureStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SELECTED = "SELECTED"


class VentureListingApprovalStatus(str, Enum):
    """Admin approval for venture marketplace visibility."""

    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
