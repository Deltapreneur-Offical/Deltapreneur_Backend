from enum import Enum


class CommunityAuctionDuration(str, Enum):
    ONE_DAY = "ONE_DAY"
    SEVEN_DAYS = "SEVEN_DAYS"
    FIFTEEN_DAYS = "FIFTEEN_DAYS"
    THIRTY_DAYS = "THIRTY_DAYS"
    SIXTY_DAYS = "SIXTY_DAYS"

    @property
    def days(self) -> int:
        return {
            "ONE_DAY": 1,
            "SEVEN_DAYS": 7,
            "FIFTEEN_DAYS": 15,
            "THIRTY_DAYS": 30,
            "SIXTY_DAYS": 60,
        }[self.value]