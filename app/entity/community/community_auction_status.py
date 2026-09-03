from enum import Enum


class CommunityAuctionStatus(str, Enum):
    PAYMENT_PENDING = "PAYMENT_PENDING"
    ACTIVE = "ACTIVE"
    EXTENDED = "EXTENDED"
    ENDED = "ENDED"
    COMPLETED = "COMPLETED"
    UNSOLD = "UNSOLD"
    CLOSED = "CLOSED"
