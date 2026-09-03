from enum import Enum


class LikeType(str, Enum):
    VENTURE = "VENTURE"
    DOMAIN = "DOMAIN"
    SOFTWARE = "SOFTWARE"
    COMMUNITY = "COMMUNITY"
    # Separate from COMMUNITY so VA likes never mix with Creator likes.
    VIRTUAL_ASSISTANT = "VIRTUAL_ASSISTANT"
