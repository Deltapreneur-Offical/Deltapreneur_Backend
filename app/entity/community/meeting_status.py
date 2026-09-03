"""Meeting lifecycle (mirrors Java MeetingStatus)."""

from enum import Enum


class MeetingStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
