"""Apply listing commission to domain, software, and venture prices."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.service.platform.platform_settings_service import PlatformSettingsService
from app.utils.listing_commission import compute_listing_commission


from app.utils.money import round_inr


class ListingPricingService:
    def __init__(self, session: AsyncSession) -> None:
        self._settings = PlatformSettingsService(session)

    async def resolve_domain_prices(
        self, seller_amount: float
    ) -> tuple[float, float]:
        """Return (seller_price, final_asking_price)."""
        pct = await self._settings.listing_commission_percent()
        seller, _, final = compute_listing_commission(seller_amount, pct)
        return seller, final

    async def resolve_software_prices(
        self,
        seller_amount: float,
        purchase_type: str,
        technology_type: str,
    ) -> tuple[float, float]:
        if purchase_type == "SUBSCRIPTION" and technology_type == "SOFTWARE":
            # 100% commission to HubRegistrar
            pct = 100.0
        elif purchase_type == "SUBSCRIPTION" and technology_type == "HARDWARE":
            pct = await self._settings.hardware_subscription_commission_percent()
        elif purchase_type == "ONE_TIME" and technology_type == "HARDWARE":
            pct = await self._settings.hardware_onetime_commission_percent()
        else:
            # Software One-Time (or default)
            pct = await self._settings.software_onetime_commission_percent()
            
        seller, _, final = compute_listing_commission(seller_amount, pct)
        return seller, final

    async def resolve_venture_deal_values(
        self, seller_amount: int
    ) -> tuple[int, int]:
        pct = await self._settings.listing_commission_percent()
        seller_f = float(seller_amount)
        seller, _, final = compute_listing_commission(seller_f, pct)
        return round_inr(seller), round_inr(final)

    async def commission_percent(self) -> float:
        return await self._settings.listing_commission_percent()

    async def acquisition_commission_percent(self) -> float:
        return await self._settings.venture_acquisition_commission_percent()

    async def resolve_venture_acquisition_deal_values(
        self, asking_price: int
    ) -> tuple[int, int]:
        """Return (asking_price, seller_receives) using deductive commission."""
        from app.utils.venture_acquisition_commission import compute_deductive_commission

        pct = await self.acquisition_commission_percent()
        _, _, seller_receives = compute_deductive_commission(float(asking_price), pct)
        return asking_price, round_inr(seller_receives)
