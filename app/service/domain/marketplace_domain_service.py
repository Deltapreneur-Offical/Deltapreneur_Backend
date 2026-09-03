"""Domain marketplace listing business logic."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.entity.cobranding.domain_listing_entity import DomainListing
from app.entity.coventure.agreement_entity import Agreement
from app.entity.coventure.contact_info_entity import ContactInfo
from app.entity.user.app_user import AppUser
from app.model.marketplace.domain_listing_request import (
    CreateDomainListingRequest,
    UpdateDomainListingRequest,
)
from app.model.venture.venture_request import ContactInfoRequest
from app.repository.domain_listing_repository import DomainListingRepository
from app.service.platform.listing_pricing_service import ListingPricingService
from app.utils.marketplace_enums import SaleType
from app.service.marketplace.listing_view_counter import record_domain_listing_view
from app.utils.pagination import offset_limit


class MarketplaceDomainService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DomainListingRepository(session)
        self._pricing = ListingPricingService(session)

    async def list_all(self) -> list[DomainListing]:
        return list(await self._repo.list_all_active())

    async def list_public_page(
        self,
        *,
        page: int = 1,
        page_size: int | None = None,
        featured_only: bool = False,
    ) -> tuple[int, list[DomainListing]]:
        """Return (total, items). When page_size is None, returns all active rows."""
        if featured_only:
            items = list(await self._repo.list_homepage_featured())
            return len(items), items

        if page_size is None:
            items = list(await self._repo.list_all_active())
            return len(items), items
        total = await self._repo.count_all_active()
        off, lim = offset_limit(page, page_size)
        items = list(await self._repo.list_all_active(offset=off, limit=lim))
        return total, items

    async def search_listed_non_auction(self, query: str) -> list[DomainListing]:
        if not query.strip():
            return []
        return list(await self._repo.search_active_non_auction(query))

    async def list_my_listings(self, user: AppUser) -> list[DomainListing]:
        return list(await self._repo.list_by_lister(user.id))

    async def list_my_purchases(self, user: AppUser) -> list[DomainListing]:
        return list(await self._repo.list_by_buyer(user.id))

    async def get_listing(self, listing_id: uuid.UUID) -> DomainListing:
        listing = await self._repo.get_by_id(listing_id)
        if listing is None:
            raise AppException("Domain listing not found.", status_code=404)
        return listing

    async def get_listing_and_record_view(
        self,
        listing_id: uuid.UUID,
        *,
        viewer: AppUser | None = None,
        client_ip: str | None = None,
        db: Session | None = None,
        viewer_industry: str | None = None,
        viewer_role: str | None = None,
    ) -> DomainListing:
        """Increment listing views once per authenticated viewer account."""
        listing = await self.get_listing(listing_id)
        if db is not None and await record_domain_listing_view(
            db,
            listing_id=listing.id,
            owner_user_id=listing.listed_by_user_id,
            viewer=viewer,
            client_ip=client_ip,
            viewer_industry=viewer_industry,
            viewer_role=viewer_role,
        ):
            await self._repo.increment_views(listing.id)
            await self._session.commit()
            return await self.get_listing(listing_id)
        return listing

    async def create_listing(
        self,
        payload: CreateDomainListingRequest,
        *,
        lister: AppUser,
    ) -> DomainListing:
        if await self._repo.exists_name(payload.domain_name, payload.domain_extension):
            raise AppException("A listing with this domain name already exists.", status_code=409)

        contact = ContactInfo()
        if payload.contact_info:
            for field in payload.contact_info.model_fields:
                setattr(contact, field, getattr(payload.contact_info, field))
        agreement = Agreement(terms=payload.agreement.terms if payload.agreement else False)
        self._session.add_all([contact, agreement])
        await self._session.flush()

        asking_price = float(payload.asking_price)
        seller_price = None
        listing_price = None
        commission_percent = None
        commission_amount = None
        seller_payout_amount = None
        if payload.sale_type == SaleType.ONE_TIME and asking_price > 0:
            seller_price, asking_price = await self._pricing.resolve_domain_prices(
                asking_price
            )
            listing_price = asking_price
            commission_percent = await self._pricing.commission_percent()
            commission_amount = float(listing_price) - float(seller_price)
            seller_payout_amount = seller_price

        listing = DomainListing(
            domain_name=payload.domain_name.strip().lower(),
            domain_extension=payload.domain_extension,
            domain_category=payload.domain_category,
            asking_price=asking_price,
            seller_price=seller_price,
            listing_price=listing_price,
            commission_percentage=commission_percent,
            commission_amount=commission_amount,
            seller_payout_amount=seller_payout_amount,
            pricing_demand=payload.pricing_demand,
            logo_text=payload.logo_text,
            contact_info_id=contact.id,
            agreement_id=agreement.id,
            listed_by_user_id=lister.id,
            sale_type=payload.sale_type,
        )
        listing = await self._repo.create(listing)
        await self._session.commit()
        return await self.get_listing(listing.id)

    async def update_listing(
        self,
        listing_id: uuid.UUID,
        payload: UpdateDomainListingRequest,
        *,
        actor: AppUser,
    ) -> DomainListing:
        listing = await self.get_listing(listing_id)
        if listing.listed_by_user_id != actor.id:
            raise AppException("Not authorized to edit this listing.", status_code=403)

        if payload.domain_name is not None:
            ext = payload.domain_extension or listing.domain_extension
            if await self._repo.exists_name(
                payload.domain_name, ext, exclude_id=listing.id,
            ):
                raise AppException("Domain name already listed.", status_code=409)
            listing.domain_name = payload.domain_name.strip().lower()

        if payload.domain_extension is not None:
            ext = payload.domain_extension.strip()
            listing.domain_extension = ext if ext.startswith(".") else f".{ext}"
        if payload.domain_category is not None:
            listing.domain_category = payload.domain_category
        if payload.asking_price is not None:
            if listing.sale_type == SaleType.ONE_TIME and float(payload.asking_price) > 0:
                seller_price, final_price = await self._pricing.resolve_domain_prices(
                    float(payload.asking_price)
                )
                commission_percent = await self._pricing.commission_percent()
                listing.seller_price = seller_price
                listing.listing_price = final_price
                listing.commission_percentage = commission_percent
                listing.commission_amount = float(final_price) - float(seller_price)
                listing.seller_payout_amount = seller_price
                listing.asking_price = final_price
            else:
                listing.asking_price = float(payload.asking_price)
                listing.listing_price = float(payload.asking_price)
                listing.commission_percentage = None
                listing.commission_amount = None
                listing.seller_payout_amount = None

        if payload.pricing_demand is not None:
            listing.pricing_demand = payload.pricing_demand

        if hasattr(payload, 'logo_text') and payload.logo_text is not None:
            listing.logo_text = payload.logo_text

        if payload.contact_info and listing.contact_info:
            for field in payload.contact_info.model_fields:
                setattr(listing.contact_info, field, getattr(payload.contact_info, field))

        listing.updated_at = datetime.now(timezone.utc)
        await self._repo.save(listing)
        await self._session.commit()
        return await self.get_listing(listing_id)

    async def set_listing_logo(
        self,
        listing_id: uuid.UUID,
        logo_url: str,
        *,
        actor: AppUser,
    ) -> DomainListing:
        listing = await self.get_listing(listing_id)
        if listing.listed_by_user_id != actor.id:
            raise AppException("Not authorized to edit this listing.", status_code=403)
        listing.logo = logo_url
        listing.updated_at = datetime.now(timezone.utc)
        await self._repo.save(listing)
        await self._session.commit()
        return await self.get_listing(listing_id)

    async def delete_listing(
        self,
        listing_id: uuid.UUID,
        *,
        actor: AppUser,
    ) -> None:
        listing = await self.get_listing(listing_id)
        if listing.listed_by_user_id != actor.id:
            raise AppException("Not authorized.", status_code=403)

        now = datetime.now(timezone.utc)
        listing.is_deleted = True
        listing.deleted_at = now
        listing.deleted_by = actor.id
        listing.updated_at = now
        await self._repo.save(listing)
        await self._session.commit()

    async def update_listing_logo(
        self,
        listing_id: uuid.UUID,
        logo_url: str,
        *,
        actor: AppUser,
    ) -> DomainListing:
        listing = await self.get_listing(listing_id)
        if listing.listed_by_user_id != actor.id:
            raise AppException("Not authorized to edit this listing.", status_code=403)
        listing.logo = logo_url
        listing.updated_at = datetime.now(timezone.utc)
        await self._repo.save(listing)
        await self._session.commit()
        return await self.get_listing(listing_id)

    async def check_availability(self, domain_name: str, extension: str = ".com") -> dict:
        taken = await self._repo.exists_name(domain_name, extension)
        return {"domainName": domain_name, "extension": extension, "available": not taken}
