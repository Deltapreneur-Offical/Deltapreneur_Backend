"""CoCreation (software marketplace) business logic."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.repository.analytics_repository import AnalyticsRepository
from app.repository.software_purchase_repository import SoftwarePurchaseRepository
from app.entity.cocreation.software_entity import Software
from app.entity.cocreation.technology_pricing_plan_entity import TechnologyPricingPlan
from app.entity.coventure.agreement_entity import Agreement
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.model.cocreation.cocreation_request import CreateSoftwareRequest, UpdateSoftwareRequest
from app.repository.software_auction_repository import SoftwareAuctionRepository
from app.repository.software_repository import SoftwareRepository
from app.service.platform.listing_pricing_service import ListingPricingService
from app.service.cocreation.software_auction_service import SoftwareAuctionService
from app.service.currency.exchange_rate_service import convert_foreign_to_inr
from app.utils.cocreation_enums import (
    SoftwareAuctionApprovalStatus,
    SoftwarePricingDemand,
    SoftwarePurchaseType,
    SoftwareStatus,
)


def _normalize_listing_currency(raw: str | None) -> str:
    code = (raw or "INR").strip().upper() or "INR"
    return code[:3]


def _to_stored_inr(amount: float, currency: str) -> float:
    """Persist marketplace amounts in INR (commission + checkout assume INR)."""
    value = float(amount or 0)
    if value <= 0:
        return 0.0
    code = _normalize_listing_currency(currency)
    if code == "INR":
        return value
    try:
        return float(convert_foreign_to_inr(value, code)["amountInr"])
    except Exception as exc:
        raise AppException(
            f"Could not convert {code} price to INR for listing storage.",
            status_code=400,
        ) from exc


def _can_manage_software(software: Software, actor: AppUser) -> bool:
    """Owner, or platform admin, may edit/delete technology listings."""
    if software.listed_by_user_id == actor.id:
        return True
    role = getattr(actor, "role", None)
    return role in (UserRole.ADMIN, UserRole.SUPER_ADMIN)


class CocreationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SoftwareRepository(session)
        self._auction_repo = SoftwareAuctionRepository(session)
        self._pricing = ListingPricingService(session)

    async def list_public_page(
        self,
        *,
        page: int = 1,
        page_size: int | None = None,
        featured_only: bool = False,
    ) -> tuple[int, list[Software]]:
        from app.utils.pagination import offset_limit

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

    async def list_all(self) -> list[Software]:
        rows = list(await self._repo.list_all_active())
        visible = [s for s in rows if s.software_status != SoftwareStatus.PENDING]
        if not visible:
            return visible
        auction_map = await self._auction_repo.map_by_software_ids(
            [s.id for s in visible],
        )
        return [
            s
            for s in visible
            if not (
                s.purchase_type == SoftwarePurchaseType.AUCTION
                and (auction := auction_map.get(s.id)) is not None
                and auction.approval_status
                == SoftwareAuctionApprovalStatus.PENDING_APPROVAL
            )
        ]

    async def list_my(self, user: AppUser) -> list[Software]:
        return list(await self._repo.list_by_lister(user.id))

    async def list_my_purchases(self, user: AppUser) -> list:
        from app.model.cocreation.purchase_mapper import build_purchase_response
        from app.entity.technology_services.technology_subscription_entity import TechnologySubscriptionEntity
        from sqlalchemy import select as sa_select

        purchase_repo = SoftwarePurchaseRepository(self._session)
        rows = await purchase_repo.list_completed_by_buyer(user.id)
        result = [build_purchase_response(p) for p in rows]

        stmt = (
            sa_select(TechnologySubscriptionEntity)
            .where(
                TechnologySubscriptionEntity.user_id == str(user.id),
                TechnologySubscriptionEntity.is_deleted == False,
            )
            .order_by(TechnologySubscriptionEntity.created_at.desc())
        )
        res = await self._session.execute(stmt)
        tech_subs = res.scalars().all()

        for sub in tech_subs:
            result.append({
                "id": str(sub.id),
                "softwareId": str(sub.id),
                "buyerId": str(sub.user_id),
                "buyerFullName": None,
                "buyerEmail": None,
                "buyerPhone": None,
                "paymentStatus": "COMPLETED",
                "completionStatus": "ACTIVE" if sub.status == "ACTIVE" else "PENDING",
                "selectedPlan": sub.plan_code,
                "expiryDate": sub.current_period_end.isoformat() if sub.current_period_end else None,
                "coBrotherOptIn": False,
                "coBrotherHelpPaid": False,
                "grossAmountInr": float(sub.price or 0),
                "soldAt": sub.current_period_start.isoformat() if sub.current_period_start else None,
                "createdAt": sub.created_at.isoformat() if sub.created_at else None,
                "software": {
                    "name": sub.service_name,
                    "category": "Technology",
                    "technologyType": "SOFTWARE",
                    "price": sub.price,
                    "githubLink": None,
                    "demoUrl": None,
                },
            })

        return result

    async def get_software(self, software_id: uuid.UUID) -> Software:
        software = await self._repo.get_by_id(software_id)
        if software is None:
            raise AppException("Software listing not found.", status_code=404)
        return software

    async def create_software(
        self,
        payload: CreateSoftwareRequest,
        *,
        lister: AppUser,
    ) -> Software:
        agreement = Agreement(terms=payload.agreement.terms if payload.agreement else False)
        self._session.add(agreement)
        await self._session.flush()

        list_price = float(payload.price)
        listing_currency = _normalize_listing_currency(payload.currency)
        list_price = _to_stored_inr(list_price, listing_currency)
        seller_price = None
        if payload.purchase_type == SoftwarePurchaseType.AUCTION and payload.min_bid_price:
            list_price = _to_stored_inr(float(payload.min_bid_price), listing_currency)
        elif payload.purchase_type == SoftwarePurchaseType.ONE_TIME and list_price > 0:
            seller_price, list_price = await self._pricing.resolve_software_prices(
                list_price,
                purchase_type=payload.purchase_type.value,
                technology_type=payload.technology_type.value,
            )

        software = Software(
            name=payload.name,
            description=payload.description,
            video_link=payload.video_link,
            what_it_does=payload.what_it_does,
            how_it_helps=payload.how_it_helps,
            github_link=payload.github_link,
            documentation_urls=payload.documentation_urls,
            download_urls=payload.download_urls,
            live_demo_link=payload.live_demo_link,
            tech_stack=payload.tech_stack,
            technology_type=payload.technology_type,
            category=payload.category,
            pricing_demand=(
                None if payload.purchase_type == SoftwarePurchaseType.AUCTION
                else payload.pricing_demand or SoftwarePricingDemand.FIXED
            ),
            price=list_price,
            seller_price=seller_price,
            currency=listing_currency,
            purchase_type=payload.purchase_type,
            agreement_id=agreement.id,
            listed_by_user_id=lister.id,
            verified=False,
        )

        if payload.pricing_plans:
            from app.utils.cocreation_enums import TechnologyPricingPlanDuration
            for plan_duration, p_price in payload.pricing_plans.items():
                # Convert string to enum if needed
                if isinstance(plan_duration, str):
                    plan_duration = TechnologyPricingPlanDuration(plan_duration)
                p_inr = _to_stored_inr(float(p_price), listing_currency)
                p_seller_price, p_final_price = await self._pricing.resolve_software_prices(
                    p_inr,
                    purchase_type=payload.purchase_type.value,
                    technology_type=payload.technology_type.value,
                )
                plan = TechnologyPricingPlan(
                    plan_duration=plan_duration,
                    price=p_final_price,
                    is_active=True,
                )
                software.pricing_plans.append(plan)

        software = await self._repo.create(software)

        if payload.purchase_type == SoftwarePurchaseType.AUCTION:
            if not payload.min_bid_price or not payload.auction_duration:
                raise AppException(
                    "Auction listings require minBidPrice and auctionDuration.",
                    status_code=400,
                )
            auction_service = SoftwareAuctionService(self._session)
            await auction_service.create_auction_for_new_listing(
                software.id,
                min_bid_price=_to_stored_inr(float(payload.min_bid_price), listing_currency),
                duration=payload.auction_duration,
                auction_rationale=payload.auction_rationale or "",
                source_code_included=bool(payload.source_code_included),
                support_included=bool(payload.support_included),
                support_days=int(payload.support_days or 0),
                transfer_details=payload.transfer_details,
                lister=lister,
                creation_fee_order_id=payload.creation_fee_order_id or "",
            )

        await self._session.commit()
        return await self.get_software(software.id)

    async def create_official_software(
        self,
        payload: CreateSoftwareRequest,
        *,
        admin: AppUser,
    ) -> Software:
        """Admin-listed official catalog entry (Java AdminController.listOfficialSoftware)."""
        agreement = Agreement(terms=payload.agreement.terms if payload.agreement else True)
        self._session.add(agreement)
        await self._session.flush()

        software = Software(
            name=payload.name,
            description=payload.description,
            video_link=payload.video_link,
            what_it_does=payload.what_it_does,
            how_it_helps=payload.how_it_helps,
            github_link=payload.github_link,
            documentation_urls=payload.documentation_urls,
            download_urls=payload.download_urls,
            live_demo_link=payload.live_demo_link,
            tech_stack=payload.tech_stack,
            technology_type=payload.technology_type,
            category=payload.category,
            pricing_demand=payload.pricing_demand or SoftwarePricingDemand.FIXED,
            price=_to_stored_inr(float(payload.price or 0), payload.currency),
            currency=_normalize_listing_currency(payload.currency),
            purchase_type=SoftwarePurchaseType.ONE_TIME,
            agreement_id=agreement.id,
            listed_by_user_id=admin.id,
            official=True,
            software_status=SoftwareStatus.AVAILABLE,
            featured=True,
            verified=True,
            verified_at=datetime.now(timezone.utc),
        )

        if payload.pricing_plans:
            listing_currency = _normalize_listing_currency(payload.currency)
            for plan_duration, p_price in payload.pricing_plans.items():
                p_inr = _to_stored_inr(float(p_price), listing_currency)
                p_seller_price, p_final_price = await self._pricing.resolve_software_prices(
                    p_inr,
                    purchase_type=payload.purchase_type.value,
                    technology_type=payload.technology_type.value,
                )
                plan = TechnologyPricingPlan(
                    plan_duration=plan_duration,
                    price=p_final_price,
                    is_active=True,
                )
                software.pricing_plans.append(plan)

        software = await self._repo.create(software)
        await self._session.commit()
        return await self.get_software(software.id)

    async def update_software(
        self,
        software_id: uuid.UUID,
        payload: UpdateSoftwareRequest,
        *,
        actor: AppUser,
    ) -> Software:
        software = await self.get_software(software_id)
        if not _can_manage_software(software, actor):
            raise AppException("Not authorized to edit this listing.", status_code=403)

        data = payload.model_dump(exclude_unset=True)
        listing_currency = _normalize_listing_currency(
            data.get("currency") if "currency" in data else software.currency
        )
        if "currency" in data:
            software.currency = listing_currency
            data.pop("currency", None)

        if "price" in data and software.purchase_type == SoftwarePurchaseType.ONE_TIME:
            seller_amount = _to_stored_inr(float(data.pop("price")), listing_currency)
            if seller_amount >= 0:
                seller_price, final_price = await self._pricing.resolve_software_prices(
                    seller_amount,
                    purchase_type=software.purchase_type.value,
                    technology_type=software.technology_type.value,
                )
                software.seller_price = seller_price
                software.price = final_price
                
        if "pricing_plans" in data:
            plans_data = data.pop("pricing_plans")
            if plans_data is not None:
                software.pricing_plans.clear()
                for plan_duration, p_price in plans_data.items():
                    p_inr = _to_stored_inr(float(p_price), listing_currency)
                    p_seller_price, p_final_price = await self._pricing.resolve_software_prices(
                        p_inr,
                        purchase_type=software.purchase_type.value,
                        technology_type=software.technology_type.value,
                    )
                    plan = TechnologyPricingPlan(
                        plan_duration=plan_duration,
                        price=p_final_price,
                        is_active=True,
                    )
                    software.pricing_plans.append(plan)

        for field, value in data.items():
            if field in {"agreement"}:
                continue
            setattr(software, field, value)

        software.updated_at = datetime.now(timezone.utc)
        await self._repo.save(software)
        await self._session.commit()
        return await self.get_software(software_id)

    async def delete_software(
        self,
        software_id: uuid.UUID,
        *,
        actor: AppUser,
    ) -> None:
        software = await self.get_software(software_id)
        if not _can_manage_software(software, actor):
            raise AppException("Not authorized.", status_code=403)

        now = datetime.now(timezone.utc)
        await self._auction_repo.delete_by_software_id(software.id)
        software.is_deleted = True
        software.deleted_at = now
        software.deleted_by = actor.id
        software.updated_at = now
        await self._repo.save(software)
        await self._session.commit()

    async def increment_views(self, software_id: uuid.UUID) -> None:
        software = await self.get_software(software_id)
        software.views = int(software.views or 0) + 1
        await self._repo.save(software)
        await self._session.commit()

    async def get_analytics(
        self,
        software_id: uuid.UUID,
        *,
        actor: AppUser,
        db: Session,
    ) -> dict:
        software = await self.get_software(software_id)
        if software.listed_by_user_id != actor.id:
            raise AppException(
                "Not authorized to view analytics for this listing.",
                status_code=403,
            )

        view_rows = AnalyticsRepository.list_software_views(db, software_id)
        timestamps = [row.viewed_at for row in view_rows]
        views_by_day = AnalyticsRepository.build_daily_timeline(timestamps, 30)
        by_industry = AnalyticsRepository.count_by_field(
            [row.viewer_industry for row in view_rows]
        )
        by_role = AnalyticsRepository.count_by_field(
            [row.viewer_role for row in view_rows]
        )

        purchase_repo = SoftwarePurchaseRepository(self._session)
        total_sales = await purchase_repo.count_completed_for_software(software_id)
        unit_price = float(software.price or 0)
        status = software.software_status

        # Public view counter excludes owner opens; chart uses tracked viewer rows.
        total_views = max(int(software.views or 0), len(view_rows))

        total_sales_int = int(total_sales or 0)
        total_revenue = round(float(unit_price or 0) * total_sales_int, 2)

        return {
            "softwareId": str(software.id),
            "softwareName": software.name,
            "totalViews": int(total_views or 0),
            "totalSales": total_sales_int,
            "totalRevenue": total_revenue,
            "completionStatus": (
                status.value.replace("_", " ").title() if status else "Available"
            ),
            "viewsByDay": views_by_day or {},
            "byIndustry": by_industry or {},
            "byRole": by_role or {},
        }

    async def set_software_image_url(
        self,
        software_id: uuid.UUID,
        *,
        actor: AppUser,
        image_url: str,
    ) -> Software:
        software = await self.get_software(software_id)
        if software.listed_by_user_id != actor.id:
            raise AppException("Not authorized to update this listing.", status_code=403)
        software.image_url = image_url
        software.updated_at = datetime.now(timezone.utc)
        await self._repo.save(software)
        await self._session.commit()
        return await self.get_software(software_id)

    async def list_my_sales(self, user: AppUser) -> list:
        from app.model.cocreation.purchase_mapper import build_purchase_response

        purchase_repo = SoftwarePurchaseRepository(self._session)
        rows = await purchase_repo.list_completed_by_seller(user.id)
        return [build_purchase_response(p) for p in rows]
