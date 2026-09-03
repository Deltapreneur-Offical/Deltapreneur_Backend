"""Read/write admin platform settings for auctions."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.repository.platform_settings_repository import PlatformSettingsRepository

KEY_DOMAIN_PARTICIPATION_FEE = "domain_auction_participation_fee_inr"
KEY_SOFTWARE_PARTICIPATION_FEE = "software_auction_participation_fee_inr"
KEY_COMMUNITY_PARTICIPATION_FEE = "community_auction_participation_fee_inr"
KEY_LISTING_COMMISSION_PERCENT = "listing_commission_percent"
KEY_AUCTION_CREATION_FEE = "auction_creation_fee_inr"
KEY_AUCTION_BID_FEE = "auction_bid_fee_inr"
KEY_VENTURE_ACQUISITION_COMMISSION = "venture_acquisition_commission_percent"
KEY_SOFTWARE_ONETIME_COMMISSION = "software_onetime_commission_percent"
KEY_HARDWARE_ONETIME_COMMISSION = "hardware_onetime_commission_percent"
KEY_HARDWARE_SUBSCRIPTION_COMMISSION = "hardware_subscription_commission_percent"

DEFAULT_PARTICIPATION_FEE = 118.0
DEFAULT_SOFTWARE_PARTICIPATION_FEE = 118.0
DEFAULT_LISTING_COMMISSION_PERCENT = 15.0
DEFAULT_AUCTION_CREATION_FEE = 118.0
DEFAULT_AUCTION_BID_FEE = 20.0
DEFAULT_VENTURE_ACQUISITION_COMMISSION = 3.0
DEFAULT_SOFTWARE_ONETIME_COMMISSION = 15.0
DEFAULT_HARDWARE_ONETIME_COMMISSION = 15.0
DEFAULT_HARDWARE_SUBSCRIPTION_COMMISSION = 15.0
MIN_BID_INCREMENT_PERCENT = 5


class PlatformSettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = PlatformSettingsRepository(session)
        self._session = session

    async def get_software_auction_config(self) -> dict:
        fee = await self.software_participation_fee_inr()
        return {
            "participationFeeInr": fee,
            "minBidIncrementPercent": MIN_BID_INCREMENT_PERCENT,
        }

    async def update_software_auction_config(
        self,
        *,
        participation_fee_inr: float | None = None,
    ) -> dict:
        if participation_fee_inr is not None:
            if participation_fee_inr < 1 or participation_fee_inr > 100_000:
                raise ValueError("Participation fee must be between ₹1 and ₹100,000.")
            await self._repo.set(
                KEY_SOFTWARE_PARTICIPATION_FEE,
                str(participation_fee_inr),
            )
        await self._session.commit()
        return await self.get_software_auction_config()

    async def get_all_participation_fees(self) -> dict:
        return {
            "domainParticipationFeeInr": await self._get_float(
                KEY_DOMAIN_PARTICIPATION_FEE, DEFAULT_PARTICIPATION_FEE
            ),
            "softwareParticipationFeeInr": await self._get_float(
                KEY_SOFTWARE_PARTICIPATION_FEE, DEFAULT_PARTICIPATION_FEE
            ),
            "communityParticipationFeeInr": await self._get_float(
                KEY_COMMUNITY_PARTICIPATION_FEE, DEFAULT_PARTICIPATION_FEE
            ),
        }

    async def update_all_participation_fees(
        self,
        *,
        domain_fee_inr: float | None = None,
        software_fee_inr: float | None = None,
        community_fee_inr: float | None = None,
    ) -> dict:
        def validate(name: str, fee: float) -> None:
            if fee < 1 or fee > 100_000:
                raise ValueError(f"{name} fee must be between ₹1 and ₹100,000.")

        if domain_fee_inr is not None:
            validate("Domain auction participation", domain_fee_inr)
            await self._repo.set(KEY_DOMAIN_PARTICIPATION_FEE, str(domain_fee_inr))
        if software_fee_inr is not None:
            validate("Software auction participation", software_fee_inr)
            await self._repo.set(KEY_SOFTWARE_PARTICIPATION_FEE, str(software_fee_inr))
        if community_fee_inr is not None:
            validate("Community auction participation", community_fee_inr)
            await self._repo.set(KEY_COMMUNITY_PARTICIPATION_FEE, str(community_fee_inr))
        await self._session.commit()
        return await self.get_all_participation_fees()

    async def domain_participation_fee_inr(self) -> float:
        return await self._get_float(KEY_DOMAIN_PARTICIPATION_FEE, DEFAULT_PARTICIPATION_FEE)

    async def software_participation_fee_inr(self) -> float:
        return await self._get_float(KEY_SOFTWARE_PARTICIPATION_FEE, DEFAULT_PARTICIPATION_FEE)

    async def community_participation_fee_inr(self) -> float:
        return await self._get_float(KEY_COMMUNITY_PARTICIPATION_FEE, DEFAULT_PARTICIPATION_FEE)

    async def listing_commission_percent(self) -> float:
        return await self._get_float(
            KEY_LISTING_COMMISSION_PERCENT, DEFAULT_LISTING_COMMISSION_PERCENT
        )

    async def auction_creation_fee_inr(self) -> float:
        return await self._get_float(KEY_AUCTION_CREATION_FEE, DEFAULT_AUCTION_CREATION_FEE)

    async def auction_bid_fee_inr(self) -> float:
        return await self._get_float(KEY_AUCTION_BID_FEE, DEFAULT_AUCTION_BID_FEE)

    async def venture_acquisition_commission_percent(self) -> float:
        return await self._get_float(
            KEY_VENTURE_ACQUISITION_COMMISSION,
            DEFAULT_VENTURE_ACQUISITION_COMMISSION,
        )

    async def software_onetime_commission_percent(self) -> float:
        return await self._get_float(
            KEY_SOFTWARE_ONETIME_COMMISSION, DEFAULT_SOFTWARE_ONETIME_COMMISSION
        )

    async def hardware_onetime_commission_percent(self) -> float:
        return await self._get_float(
            KEY_HARDWARE_ONETIME_COMMISSION, DEFAULT_HARDWARE_ONETIME_COMMISSION
        )

    async def hardware_subscription_commission_percent(self) -> float:
        return await self._get_float(
            KEY_HARDWARE_SUBSCRIPTION_COMMISSION, DEFAULT_HARDWARE_SUBSCRIPTION_COMMISSION
        )

    async def get_listing_fees_and_charges(self) -> dict:
        return {
            "listingCommissionPercent": await self.listing_commission_percent(),
            "ventureAcquisitionCommissionPercent": await self.venture_acquisition_commission_percent(),
            "auctionCreationFeeInr": await self.auction_creation_fee_inr(),
            "auctionBidFeeInr": await self.auction_bid_fee_inr(),
            "domainParticipationFeeInr": await self._get_float(
                KEY_DOMAIN_PARTICIPATION_FEE, DEFAULT_PARTICIPATION_FEE
            ),
            "softwareParticipationFeeInr": await self._get_float(
                KEY_SOFTWARE_PARTICIPATION_FEE, DEFAULT_PARTICIPATION_FEE
            ),
            "communityParticipationFeeInr": await self._get_float(
                KEY_COMMUNITY_PARTICIPATION_FEE, DEFAULT_PARTICIPATION_FEE
            ),
            "softwareOnetimeCommissionPercent": await self.software_onetime_commission_percent(),
            "hardwareOnetimeCommissionPercent": await self.hardware_onetime_commission_percent(),
            "hardwareSubscriptionCommissionPercent": await self.hardware_subscription_commission_percent(),
        }

    async def update_listing_fees_and_charges(
        self,
        *,
        listing_commission_percent: float | None = None,
        venture_acquisition_commission_percent: float | None = None,
        auction_creation_fee_inr: float | None = None,
        auction_bid_fee_inr: float | None = None,
        domain_participation_fee_inr: float | None = None,
        software_participation_fee_inr: float | None = None,
        community_participation_fee_inr: float | None = None,
        software_onetime_commission_percent: float | None = None,
        hardware_onetime_commission_percent: float | None = None,
        hardware_subscription_commission_percent: float | None = None,
    ) -> dict:
        if listing_commission_percent is not None:
            if listing_commission_percent < 0 or listing_commission_percent > 100:
                raise ValueError("Listing commission must be between 0% and 100%.")
            await self._repo.set(
                KEY_LISTING_COMMISSION_PERCENT, str(listing_commission_percent)
            )
        if venture_acquisition_commission_percent is not None:
            if (
                venture_acquisition_commission_percent < 0
                or venture_acquisition_commission_percent > 100
            ):
                raise ValueError(
                    "Venture acquisition commission must be between 0% and 100%."
                )
            await self._repo.set(
                KEY_VENTURE_ACQUISITION_COMMISSION,
                str(venture_acquisition_commission_percent),
            )
        if auction_creation_fee_inr is not None:
            if auction_creation_fee_inr < 1 or auction_creation_fee_inr > 100_000:
                raise ValueError("Auction creation fee must be between ₹1 and ₹100,000.")
            await self._repo.set(KEY_AUCTION_CREATION_FEE, str(auction_creation_fee_inr))
        if auction_bid_fee_inr is not None:
            if auction_bid_fee_inr < 1 or auction_bid_fee_inr > 100_000:
                raise ValueError("Auction bid fee must be between ₹1 and ₹100,000.")
            await self._repo.set(KEY_AUCTION_BID_FEE, str(auction_bid_fee_inr))

        def _validate_tech_pct(name: str, pct: float) -> None:
            if pct < 0 or pct > 100:
                raise ValueError(f"{name} commission must be between 0% and 100%.")

        if software_onetime_commission_percent is not None:
            _validate_tech_pct("Software One-Time", software_onetime_commission_percent)
            await self._repo.set(
                KEY_SOFTWARE_ONETIME_COMMISSION, str(software_onetime_commission_percent)
            )
        if hardware_onetime_commission_percent is not None:
            _validate_tech_pct("Hardware One-Time", hardware_onetime_commission_percent)
            await self._repo.set(
                KEY_HARDWARE_ONETIME_COMMISSION, str(hardware_onetime_commission_percent)
            )
        if hardware_subscription_commission_percent is not None:
            _validate_tech_pct(
                "Hardware Subscription", hardware_subscription_commission_percent
            )
            await self._repo.set(
                KEY_HARDWARE_SUBSCRIPTION_COMMISSION,
                str(hardware_subscription_commission_percent),
            )

        if any(
            fee is not None
            for fee in (
                domain_participation_fee_inr,
                software_participation_fee_inr,
                community_participation_fee_inr,
            )
        ):
            await self.update_all_participation_fees(
                domain_fee_inr=domain_participation_fee_inr,
                software_fee_inr=software_participation_fee_inr,
                community_fee_inr=community_participation_fee_inr,
            )

        await self._session.commit()
        return await self.get_listing_fees_and_charges()

    async def update_technology_commissions(
        self,
        *,
        software_onetime_commission_percent: float | None = None,
        hardware_onetime_commission_percent: float | None = None,
        hardware_subscription_commission_percent: float | None = None,
    ) -> dict:
        def validate(name: str, pct: float) -> None:
            if pct < 0 or pct > 100:
                raise ValueError(f"{name} commission must be between 0% and 100%.")

        if software_onetime_commission_percent is not None:
            validate("Software One-Time", software_onetime_commission_percent)
            await self._repo.set(KEY_SOFTWARE_ONETIME_COMMISSION, str(software_onetime_commission_percent))
        if hardware_onetime_commission_percent is not None:
            validate("Hardware One-Time", hardware_onetime_commission_percent)
            await self._repo.set(KEY_HARDWARE_ONETIME_COMMISSION, str(hardware_onetime_commission_percent))
        if hardware_subscription_commission_percent is not None:
            validate("Hardware Subscription", hardware_subscription_commission_percent)
            await self._repo.set(KEY_HARDWARE_SUBSCRIPTION_COMMISSION, str(hardware_subscription_commission_percent))
            
        await self._session.commit()
        return await self.get_listing_fees_and_charges()

    async def _get_float(self, key: str, default: float) -> float:
        raw = await self._repo.get(key)
        if raw is None:
            return default
        try:
            return float(raw.strip())
        except ValueError:
            return default
