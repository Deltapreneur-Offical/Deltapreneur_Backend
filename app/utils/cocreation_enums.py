"""CoCreation (software marketplace) enums."""

from __future__ import annotations

from enum import Enum


class TechnologyType(str, Enum):
    SOFTWARE = "SOFTWARE"
    HARDWARE = "HARDWARE"


class TechnologyPricingPlanDuration(str, Enum):
    ONE_TIME = "ONE_TIME"
    ONE_MONTH = "ONE_MONTH"
    THREE_MONTHS = "THREE_MONTHS"
    SIX_MONTHS = "SIX_MONTHS"
    TWELVE_MONTHS = "TWELVE_MONTHS"


class SoftwareCategory(str, Enum):
    WEB_APP = "WEB_APP"
    MOBILE_APP = "MOBILE_APP"
    DESKTOP = "DESKTOP"
    SAAS = "SAAS"
    API = "API"
    API_TOOL = "API_TOOL"
    PLUGIN = "PLUGIN"
    TEMPLATE = "TEMPLATE"
    AUTOMATION = "AUTOMATION"
    ECOMMERCE = "ECOMMERCE"
    EDUCATION = "EDUCATION"
    OTHER = "OTHER"
    
    # Hardware Categories
    IOT_DEVICE = "IOT_DEVICE"
    CONSUMER_ELECTRONICS = "CONSUMER_ELECTRONICS"
    INDUSTRIAL_EQUIPMENT = "INDUSTRIAL_EQUIPMENT"
    MEDICAL_DEVICE = "MEDICAL_DEVICE"
    NETWORKING_EQUIPMENT = "NETWORKING_EQUIPMENT"
    ROBOTICS = "ROBOTICS"
    EMBEDDED_SYSTEM = "EMBEDDED_SYSTEM"
    SECURITY_DEVICE = "SECURITY_DEVICE"
    SMART_HOME = "SMART_HOME"
    COMPONENTS = "COMPONENTS"
    MANUFACTURING_EQUIPMENT = "MANUFACTURING_EQUIPMENT"


class SoftwarePricingDemand(str, Enum):
    NEGOTIABLE = "NEGOTIABLE"
    FIXED = "FIXED"


class SoftwareStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SOLD = "SOLD"
    PENDING = "PENDING"


class SoftwarePurchaseType(str, Enum):
    ONE_TIME = "ONE_TIME"
    SUBSCRIPTION = "SUBSCRIPTION"
    AUCTION = "AUCTION"


class SoftwarePaymentStatus(str, Enum):
    CREATED = "CREATED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SoftwarePurchaseCompletionStatus(str, Enum):
    """Buyer confirms the software works before GitHub access is finalized."""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"


class SoftwareAuctionDuration(str, Enum):
    """Software auction lengths.

    FIFTEEN_DAYS is kept for rows created by the legacy Java backend
    (AuctionDuration.ONE_DAY / SEVEN_DAYS / FIFTEEN_DAYS / THIRTY_DAYS).
    """

    ONE_DAY = "ONE_DAY"
    THREE_DAYS = "THREE_DAYS"
    FIVE_DAYS = "FIVE_DAYS"
    SEVEN_DAYS = "SEVEN_DAYS"
    FOURTEEN_DAYS = "FOURTEEN_DAYS"
    FIFTEEN_DAYS = "FIFTEEN_DAYS"
    THIRTY_DAYS = "THIRTY_DAYS"

    def to_days(self) -> int:
        return {
            SoftwareAuctionDuration.ONE_DAY: 1,
            SoftwareAuctionDuration.THREE_DAYS: 3,
            SoftwareAuctionDuration.FIVE_DAYS: 5,
            SoftwareAuctionDuration.SEVEN_DAYS: 7,
            SoftwareAuctionDuration.FOURTEEN_DAYS: 14,
            SoftwareAuctionDuration.FIFTEEN_DAYS: 15,
            SoftwareAuctionDuration.THIRTY_DAYS: 30,
        }[self]


class SoftwareAuctionApprovalStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
