from enum import Enum


class UserRole(str, Enum):

    USER = "USER"

    GUEST = "GUEST"

    ADMIN = "ADMIN"

    SUPER_ADMIN = "SUPER_ADMIN"

    AUCTION_MODERATOR = "AUCTION_MODERATOR"

    COBROTHER = "COBROTHER"

