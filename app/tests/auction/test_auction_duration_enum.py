from app.utils.enums import AuctionDuration


def test_domain_auction_durations_use_the_new_public_options():
    assert [member.value for member in AuctionDuration] == [
        "ONE_DAY",
        "SEVEN_DAYS",
        "THIRTY_DAYS",
        "SIXTY_DAYS",
        "NINETY_DAYS",
    ]

    assert AuctionDuration.ONE_DAY.to_seconds() == 24 * 60 * 60
    assert AuctionDuration.SEVEN_DAYS.to_seconds() == 7 * 24 * 60 * 60
    assert AuctionDuration.THIRTY_DAYS.to_seconds() == 30 * 24 * 60 * 60
    assert AuctionDuration.SIXTY_DAYS.to_seconds() == 60 * 24 * 60 * 60
    assert AuctionDuration.NINETY_DAYS.to_seconds() == 90 * 24 * 60 * 60
