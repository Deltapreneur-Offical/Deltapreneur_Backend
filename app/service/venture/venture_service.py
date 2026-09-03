"""Venture listing business logic."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.coventure.agreement_entity import Agreement
from app.entity.coventure.brand_details_entity import BrandDetails
from app.entity.coventure.contact_info_entity import ContactInfo
from app.entity.coventure.venture_company_profile_entity import VentureCompanyProfile
from app.entity.coventure.venture_entity import Venture
from app.entity.coventure.venture_role_entity import VentureRole
from app.entity.notification.notification_type import NotificationType
from app.entity.user.app_user import AppUser
from app.model.venture.venture_request import (
    AgreementRequest,
    BrandDetailsRequest,
    CompanyProfileRequest,
    ContactInfoRequest,
    CreateVentureRequest,
    UpdateVentureRequest,
    VentureRoleRequest,
)
from app.repository.venture_pitch_repository import VenturePitchRepository
from app.repository.venture_repository import VentureRepository
from app.service.platform.listing_pricing_service import ListingPricingService
from app.utils.field_validators import blank_to_none
from app.utils.equity_percent import normalize_equity_percent
from app.utils.money import round_inr
from app.utils.venture_enums import (
    VentureAcquisitionFlow,
    VentureDealType,
    VentureListingApprovalStatus,
    VentureListingMode,
    VentureListingStatus,
    VentureSaleType,
    VentureStage,
    VentureVerificationStatus,
)
from app.utils.venture_visibility import can_view_venture_listing


# Public-tier fields that must be filled before an admin can approve a listing.
COMPANY_PROFILE_REQUIRED_FIELDS = (
    "company_name",
    "industry",
    "business_description",
    "products_services",
    "target_market",
    "business_model",
    "public_contact_person",
    "public_email",
)


def _parse_incorporation_date(value: str | None):
    if not value:
        return None
    from datetime import date

    try:
        return date.fromisoformat(value)
    except ValueError:
        raise AppException(
            "incorporation_date must be in YYYY-MM-DD format.", status_code=400,
        )


def _apply_company_profile(
    profile: VentureCompanyProfile,
    payload: CompanyProfileRequest,
    *,
    exclude_unset: bool = False,
) -> None:
    data = payload.model_dump(exclude_unset=exclude_unset)
    team_members = data.pop("team_members", None)
    data["incorporation_date"] = _parse_incorporation_date(data.get("incorporation_date"))
    for field, value in data.items():
        setattr(profile, field, _coerce_optional_text(value))
    if team_members is not None:
        profile.team_members = [
            {
                "name": member["name"],
                "role": member["role"],
                "equity_percent": member["equity_percent"],
                "linkedin_url": member.get("linkedin_url"),
            }
            for member in team_members
        ]
    if profile.current_year_revenue_inr is not None:
        profile.annual_revenue_inr = profile.current_year_revenue_inr
    profile.is_complete = all(
        (getattr(profile, f) or "").strip() for f in COMPANY_PROFILE_REQUIRED_FIELDS
    )
    profile.completed_at = (
        datetime.now(timezone.utc) if profile.is_complete else None
    )


def _apply_verification_fields(
    venture: Venture,
    *,
    requested: bool | None,
    video_url: str | None,
) -> None:
    if requested is not None:
        venture.verification_requested = requested
    if video_url is not None:
        venture.verification_video_url = video_url
    if venture.verification_requested:
        if venture.verification_status in (
            VentureVerificationStatus.NONE,
            VentureVerificationStatus.REJECTED,
        ):
            venture.verification_status = VentureVerificationStatus.PENDING
            venture.verification_rejection_reason = None
    elif requested is False and venture.verification_status == VentureVerificationStatus.PENDING:
        venture.verification_status = VentureVerificationStatus.NONE


def _notify_verification_requested(venture: Venture) -> None:
    from app.service.venture.venture_pitch_service import _notify_admins_sync, _notify_sync

    brand_name = (
        venture.brand_details.brand_name if venture.brand_details else "A venture"
    )
    if venture.listed_by_user_id:
        _notify_sync(
            venture.listed_by_user_id,
            notification_type=NotificationType.VENTURE_VERIFICATION_REQUESTED,
            title="Verification Requested",
            message=f"Your verification request for {brand_name} was submitted.",
            target_url="/ventures/dashboard",
        )
    _notify_admins_sync(
        notification_type=NotificationType.VENTURE_VERIFICATION_REQUESTED,
        title="Venture Verification Requested",
        message=f"{brand_name} requested listing verification.",
        target_url="/admin",
    )


def _coerce_optional_text(value: object) -> object:
    if isinstance(value, Enum):
        return value
    if isinstance(value, str):
        return blank_to_none(value)
    return value


_BRAND_PRICING_FIELDS = frozenset({"deal_value", "seller_deal_value"})


def _apply_brand_details(entity: BrandDetails, payload: BrandDetailsRequest) -> None:
    for field in BrandDetailsRequest.model_fields:
        if field in _BRAND_PRICING_FIELDS:
            continue
        setattr(
            entity,
            field,
            _coerce_optional_text(getattr(payload, field)),
        )


def _normalize_asking_inr(raw_deal_value: int | float | None) -> int | None:
    if raw_deal_value is None:
        return None
    asking = round_inr(raw_deal_value)
    return asking if asking > 0 else None


def _apply_contact_info(entity: ContactInfo, payload: ContactInfoRequest) -> None:
    for field in ContactInfoRequest.model_fields:
        setattr(
            entity,
            field,
            _coerce_optional_text(getattr(payload, field)),
        )


def _serialize_venture_purchase(
    venture: Venture,
    *,
    source: str,
) -> dict:
    brand = venture.brand_details
    amount: float | None = None
    purchased_at = venture.updated_at

    if brand is not None and brand.deal_value is not None:
        amount = float(brand.deal_value)

    industry = brand.industry if brand is not None else None
    if hasattr(industry, "value"):
        industry = industry.value

    return {
        "id": str(venture.id),
        "ventureId": str(venture.id),
        "brandName": brand.brand_name if brand else None,
        "industry": industry,
        "amount": amount,
        "purchaseSource": source,
        "purchasedAt": purchased_at.isoformat() if purchased_at else None,
    }


def _role_numeric(*values: object) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            num = float(value)
        except (TypeError, ValueError):
            continue
        if num >= 0:
            return num
    return None


def _build_roles(venture: Venture, roles: list[VentureRoleRequest]) -> None:
    venture.roles.clear()
    primary_equity: float | None = None
    for idx, role_dto in enumerate(roles):
        title = (role_dto.title or role_dto.role_offer or "").strip() or None
        equity_offer = _role_numeric(
            role_dto.equity_offer,
            role_dto.equity_min,
            role_dto.equity_max,
        )
        investment_seeking = _role_numeric(
            role_dto.investment_seeking,
            role_dto.investment_min,
            role_dto.investment_max,
        )
        if primary_equity is None and equity_offer is not None:
            primary_equity = equity_offer
        role = VentureRole(
            venture=venture,
            sort_order=idx,
            type=role_dto.type or "CO_FOUNDER",
            title=title,
            skill_domain=role_dto.skill_domain,
            description=role_dto.description,
            commitment=role_dto.commitment,
            location=role_dto.location,
            experience_level=role_dto.experience_level,
            equity_min=equity_offer,
            equity_max=equity_offer,
            vesting_terms=role_dto.vesting_terms,
            salary_min=role_dto.salary_min,
            salary_max=role_dto.salary_max,
            budget_min=role_dto.budget_min,
            budget_max=role_dto.budget_max,
            investment_min=investment_seeking,
            investment_max=investment_seeking,
        )
        venture.roles.append(role)
    if venture.listing_mode == VentureListingMode.CO_VENTURE and primary_equity is not None:
        venture.equity_percent_offered = normalize_equity_percent(primary_equity)


def _backfill_coventure_role_fields(venture: Venture) -> None:
    """Repair legacy co-venture rows missing role equity/investment snapshots."""
    if (venture.listing_mode or VentureListingMode.VENTURE) != VentureListingMode.CO_VENTURE:
        return
    venture_equity = normalize_equity_percent(venture.equity_percent_offered)
    profile = getattr(venture, "company_profile", None)
    valuation = getattr(profile, "valuation_inr", None) if profile else None
    for role in venture.roles or []:
        if role.equity_min is None and venture_equity is not None:
            role.equity_min = float(venture_equity)
            role.equity_max = float(venture_equity)
        if role.investment_min is not None:
            continue
        brand = venture.brand_details
        for candidate in (
            getattr(brand, "seller_deal_value", None) if brand else None,
            getattr(brand, "deal_value", None) if brand else None,
            valuation,
        ):
            if candidate is None:
                continue
            amount = float(candidate)
            if amount >= 0:
                role.investment_min = amount
                role.investment_max = amount
                break


class VentureService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = VentureRepository(session)
        self._pricing = ListingPricingService(session)
        self._pitches = VenturePitchRepository(session)

    async def list_all(self) -> list[Venture]:
        return list(await self._repo.list_all())

    async def list_public_page(
        self,
        *,
        page: int = 1,
        page_size: int | None = None,
        listing_mode: VentureListingMode | None = None,
        featured_only: bool = False,
        include_pending: bool = False,
    ) -> tuple[int, list[Venture]]:
        from app.utils.pagination import offset_limit

        if featured_only:
            items = list(
                await self._repo.list_homepage_featured(
                    listing_mode=listing_mode,
                )
            )
            return len(items), items

        if page_size is None:
            items = list(await self._repo.list_all(listing_mode=listing_mode, include_pending=include_pending))
            return len(items), items
        total = await self._repo.count_public(listing_mode=listing_mode, include_pending=include_pending)
        off, lim = offset_limit(page, page_size)
        items = list(
            await self._repo.list_all(offset=off, limit=lim, listing_mode=listing_mode, include_pending=include_pending)
        )
        return total, items

    async def list_my(self, user: AppUser) -> list[Venture]:
        return list(await self._repo.list_by_lister(user.id))

    async def list_my_purchases(self, user: AppUser) -> list[dict]:
        seen: set[uuid.UUID] = set()
        items: list[dict] = []

        for venture in await self._repo.list_by_buyer(user.id):
            seen.add(venture.id)
            items.append(_serialize_venture_purchase(venture, source="direct"))

        items.sort(key=lambda row: row.get("purchasedAt") or "", reverse=True)
        return items

    async def get_venture(self, venture_id: uuid.UUID) -> Venture:
        venture = await self._repo.get_by_id(venture_id)
        if venture is None:
            raise AppException("Venture not found.", status_code=404)
        return venture

    async def pitch_count_for_venture(self, venture_id: uuid.UUID) -> int:
        return await self._pitches.count_for_venture(venture_id)

    async def pitch_counts_for_ventures(
        self,
        ventures: Sequence[Venture],
    ) -> dict[uuid.UUID, int]:
        return await self._pitches.count_by_venture_ids([v.id for v in ventures])

    @staticmethod
    def _is_marketplace_visible(venture: Venture) -> bool:
        return (
            not venture.taken_down
            and venture.status
            and venture.listing_approval_status == VentureListingApprovalStatus.APPROVED
        )

    async def get_venture_for_viewer(
        self,
        venture_id: uuid.UUID,
        viewer: AppUser | None,
    ) -> Venture:
        venture = await self.get_venture(venture_id)
        active_applicant_id = await self._pitches.get_active_applicant_user_id(
            venture_id,
        )
        if can_view_venture_listing(
            venture,
            viewer,
            active_applicant_user_id=active_applicant_id,
        ):
            return venture
        raise AppException("Venture not found.", status_code=404)

    async def create_venture(
        self,
        payload: CreateVentureRequest,
        *,
        lister: AppUser,
    ) -> Venture:
        listing_mode = payload.listing_mode or VentureListingMode.VENTURE
        if listing_mode == VentureListingMode.CO_VENTURE and not payload.roles:
            raise AppException(
                "At least one role is required for co-venture listings.",
                status_code=400,
            )

        brand = BrandDetails()
        acquisition_pct = await self._pricing.acquisition_commission_percent()

        if payload.brand_details:
            _apply_brand_details(brand, payload.brand_details)
            if listing_mode == VentureListingMode.CO_VENTURE:
                brand.venture_type = None
            asking = _normalize_asking_inr(payload.brand_details.deal_value)
            if asking is not None:
                listing_price, seller_receives = (
                    await self._pricing.resolve_venture_acquisition_deal_values(asking)
                )
                brand.deal_value = listing_price
                brand.seller_deal_value = seller_receives
        contact = ContactInfo()
        if payload.contact_info:
            _apply_contact_info(contact, payload.contact_info)
        agreement = Agreement(terms=payload.agreement.terms if payload.agreement else False)

        self._session.add_all([brand, contact, agreement])
        await self._session.flush()

        acquisition_flow_value = VentureAcquisitionFlow.SELLER_SELECTS
        if listing_mode == VentureListingMode.VENTURE:
            if payload.deal_type == VentureDealType.FULL_ACQUISITION:
                acquisition_flow_value = VentureAcquisitionFlow.SELLER_SELECTS

        venture = Venture(
            brand_details_id=brand.id,
            contact_info_id=contact.id,
            agreement_id=agreement.id,
            listed_by_user_id=lister.id,
            status=payload.status,
            stage=payload.stage,
            current_problem=_coerce_optional_text(payload.current_problem),
            looking_for=_coerce_optional_text(payload.looking_for),
            sale_type=VentureSaleType.REGULAR,
            listing_mode=listing_mode,
            venture_listing_status=VentureListingStatus.ACTIVE,
            deal_type=(
                payload.deal_type
                if listing_mode == VentureListingMode.VENTURE and payload.deal_type is not None
                else None
            ),
            acquisition_flow=acquisition_flow_value,
            equity_percent_offered=(
                normalize_equity_percent(payload.equity_percent_offered)
                if listing_mode in (
                    VentureListingMode.VENTURE,
                    VentureListingMode.CO_VENTURE,
                )
                else None
            ),
            valuation_amount=payload.valuation_amount,
            commission_percent_applied=acquisition_pct,
            listing_approval_status=VentureListingApprovalStatus.PENDING_APPROVAL,
            verification_requested=payload.verification_requested,
            verification_video_url=payload.verification_video_url,
            verification_status=(
                VentureVerificationStatus.PENDING
                if payload.verification_requested
                else VentureVerificationStatus.NONE
            ),
        )
        _build_roles(venture, payload.roles)
        if listing_mode == VentureListingMode.CO_VENTURE:
            _backfill_coventure_role_fields(venture)
        if payload.company_profile is not None:
            profile = VentureCompanyProfile()
            _apply_company_profile(profile, payload.company_profile)
            venture.company_profile = profile
        venture = await self._repo.create(venture)
        await self._session.commit()

        if payload.verification_requested:
            _notify_verification_requested(venture)

        brand_name = (
            payload.brand_details.brand_name
            if payload.brand_details and payload.brand_details.brand_name
            else "A venture"
        )
        from app.service.venture.venture_pitch_service import _notify_admins_sync, _notify_sync

        _notify_admins_sync(
            notification_type=NotificationType.VENTURE_LISTING_SUBMITTED,
            title="Venture Listing Pending Approval",
            message=f"{brand_name} was submitted and is awaiting approval.",
            target_url="/admin",
        )
        _notify_sync(
            lister.id,
            notification_type=NotificationType.VENTURE_LISTING_SUBMITTED,
            title="Listing Submitted",
            message=f"{brand_name} was submitted and is pending admin approval.",
            target_url="/ventures/dashboard",
        )
        return await self._repo.get_by_id(venture.id) or venture

    async def update_venture(
        self,
        venture_id: uuid.UUID,
        payload: UpdateVentureRequest,
        *,
        actor: AppUser,
    ) -> Venture:
        venture = await self.get_venture(venture_id)
        if venture.listed_by_user_id != actor.id:
            raise AppException("You are not authorized to edit this venture.", status_code=403)

        if payload.brand_details and venture.brand_details:
            existing_image = venture.brand_details.venture_image_url
            deal_value = payload.brand_details.deal_value
            _apply_brand_details(venture.brand_details, payload.brand_details)
            if venture.listing_mode == VentureListingMode.CO_VENTURE:
                venture.brand_details.venture_type = None
            if existing_image:
                venture.brand_details.venture_image_url = existing_image
            asking = _normalize_asking_inr(deal_value)
            if asking is not None:
                if venture.listing_mode == VentureListingMode.VENTURE:
                    listing_price, seller_receives = (
                        await self._pricing.resolve_venture_acquisition_deal_values(
                            asking,
                        )
                    )
                    venture.brand_details.deal_value = listing_price
                    venture.brand_details.seller_deal_value = seller_receives
                else:
                    seller_deal, final_deal = await self._pricing.resolve_venture_deal_values(
                        asking,
                    )
                    venture.brand_details.seller_deal_value = seller_deal
                    venture.brand_details.deal_value = final_deal

        if payload.contact_info and venture.contact_info:
            _apply_contact_info(venture.contact_info, payload.contact_info)

        if payload.agreement and venture.agreement:
            venture.agreement.terms = payload.agreement.terms

        if payload.status is not None:
            venture.status = payload.status
        if payload.stage is not None:
            venture.stage = payload.stage
        if payload.current_problem is not None:
            venture.current_problem = _coerce_optional_text(payload.current_problem)
        if payload.looking_for is not None:
            venture.looking_for = _coerce_optional_text(payload.looking_for)

        if payload.equity_percent_offered is not None:
            if venture.listing_mode in (
                VentureListingMode.VENTURE,
                VentureListingMode.CO_VENTURE,
            ):
                venture.equity_percent_offered = normalize_equity_percent(
                    payload.equity_percent_offered
                )
                if venture.listing_mode == VentureListingMode.VENTURE:
                    venture.acquisition_flow = VentureAcquisitionFlow.SELLER_SELECTS

        if payload.sale_type is not None:
            venture.sale_type = payload.sale_type

        if payload.roles is not None:
            _build_roles(venture, payload.roles)
        if venture.listing_mode == VentureListingMode.CO_VENTURE:
            _backfill_coventure_role_fields(venture)

        if venture.deal_type == VentureDealType.FULL_ACQUISITION:
            venture.acquisition_flow = VentureAcquisitionFlow.SELLER_SELECTS
        elif payload.acquisition_flow is not None:
            venture.acquisition_flow = payload.acquisition_flow

        if payload.company_profile is not None:
            profile = venture.company_profile or VentureCompanyProfile()
            _apply_company_profile(
                profile, payload.company_profile, exclude_unset=True,
            )
            venture.company_profile = profile

        verification_changed = False
        if payload.verification_requested is not None or payload.verification_video_url is not None:
            previous_status = venture.verification_status
            _apply_verification_fields(
                venture,
                requested=payload.verification_requested,
                video_url=payload.verification_video_url,
            )
            verification_changed = (
                venture.verification_status == VentureVerificationStatus.PENDING
                and previous_status != VentureVerificationStatus.PENDING
            )

        venture.updated_at = datetime.now(timezone.utc)
        await self._repo.save(venture)
        await self._session.commit()
        if verification_changed:
            refreshed = await self.get_venture(venture_id)
            _notify_verification_requested(refreshed)
        if venture.listing_mode == VentureListingMode.CO_VENTURE:
            from app.service.venture.venture_deal_service import VentureDealService

            refreshed = await self.get_venture(venture_id)
            await VentureDealService(self._session).sync_coventure_deals_for_venture(refreshed)
        return await self.get_venture(venture_id)

    async def upsert_company_profile(
        self,
        venture_id: uuid.UUID,
        payload: CompanyProfileRequest,
        *,
        actor: AppUser,
    ) -> Venture:
        venture = await self.get_venture(venture_id)
        if venture.listed_by_user_id != actor.id:
            raise AppException("You are not authorized to edit this venture.", status_code=403)
        profile = venture.company_profile or VentureCompanyProfile()
        _apply_company_profile(profile, payload, exclude_unset=True)
        venture.company_profile = profile
        venture.updated_at = datetime.now(timezone.utc)
        await self._repo.save(venture)
        await self._session.commit()
        return await self.get_venture(venture_id)

    async def delete_venture(
        self,
        venture_id: uuid.UUID,
        *,
        actor: AppUser,
    ) -> None:
        venture = await self.get_venture(venture_id)
        if venture.listed_by_user_id != actor.id:
            raise AppException("You are not authorized to delete this venture.", status_code=403)

        now = datetime.now(timezone.utc)
        venture.is_deleted = True
        venture.deleted_at = now
        venture.deleted_by = actor.id
        venture.updated_at = now
        await self._repo.save(venture)
        await self._session.commit()

    async def increment_views(self, venture_id: uuid.UUID) -> None:
        venture = await self.get_venture(venture_id)
        venture.views += 1
        await self._repo.save(venture)
        await self._session.commit()

    async def update_venture_image(
        self,
        venture_id: uuid.UUID,
        image_url: str,
        *,
        actor: AppUser,
    ) -> Venture:
        venture = await self.get_venture(venture_id)
        if venture.listed_by_user_id != actor.id:
            raise AppException("You are not authorized to edit this venture.", status_code=403)
        if venture.brand_details is None:
            raise AppException("Venture has no brand details.", status_code=400)
        venture.brand_details.venture_image_url = image_url
        venture.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        await self._repo.save(venture)
        await self._session.commit()
        return await self.get_venture(venture_id)

    async def approve_listing(
        self,
        venture_id: uuid.UUID,
        *,
        admin: AppUser,
    ) -> Venture:
        venture = await self.get_venture(venture_id)
        if venture.listing_approval_status == VentureListingApprovalStatus.APPROVED:
            return venture

        profile = venture.company_profile
        if profile is None or not profile.is_complete:
            raise AppException(
                "Cannot approve: the company profile is incomplete. "
                "The owner must fill all required public fields first.",
                status_code=400,
            )

        venture.listing_approval_status = VentureListingApprovalStatus.APPROVED
        venture.listing_rejection_reason = None
        venture.listing_approved_at = datetime.now(timezone.utc)
        venture.listing_approved_by_user_id = admin.id
        venture.updated_at = datetime.now(timezone.utc)
        await self._repo.save(venture)
        await self._session.commit()

        if venture.listed_by_user_id:
            from app.service.venture.venture_pitch_service import _notify_sync

            brand = venture.brand_details
            brand_name = brand.brand_name if brand else "Your venture"
            _notify_sync(
                venture.listed_by_user_id,
                notification_type=NotificationType.VENTURE_LISTING_APPROVED,
                title="Listing Approved",
                message=f"{brand_name} is now live on the marketplace.",
                target_url="/ventures/dashboard",
            )
        return await self.get_venture(venture_id)

    async def reject_listing(
        self,
        venture_id: uuid.UUID,
        *,
        admin: AppUser,
        reason: str = "",
    ) -> Venture:
        venture = await self.get_venture(venture_id)
        venture.listing_approval_status = VentureListingApprovalStatus.REJECTED
        venture.listing_rejection_reason = (reason or "").strip() or None
        venture.listing_approved_at = None
        venture.listing_approved_by_user_id = admin.id
        venture.updated_at = datetime.now(timezone.utc)
        await self._repo.save(venture)
        await self._session.commit()

        if venture.listed_by_user_id:
            from app.service.venture.venture_pitch_service import _notify_sync

            brand = venture.brand_details
            brand_name = brand.brand_name if brand else "Your venture"
            detail = f" Reason: {venture.listing_rejection_reason}" if venture.listing_rejection_reason else ""
            _notify_sync(
                venture.listed_by_user_id,
                notification_type=NotificationType.VENTURE_LISTING_REJECTED,
                title="Listing Not Approved",
                message=f"{brand_name} was not approved.{detail}",
                target_url="/ventures/dashboard",
            )
        return await self.get_venture(venture_id)

    async def list_pending_approval(self) -> list[Venture]:
        return list(await self._repo.list_pending_approval())

    async def upload_verification_document(
        self,
        venture_id: uuid.UUID,
        *,
        actor: AppUser,
        file_url: str,
        file_name: str | None,
    ) -> Venture:
        from app.entity.coventure.venture_verification_document_entity import (
            VentureVerificationDocument,
        )

        venture = await self.get_venture(venture_id)
        if venture.listed_by_user_id != actor.id:
            raise AppException("You are not authorized to edit this venture.", status_code=403)
        doc = VentureVerificationDocument(
            venture_id=venture.id,
            file_url=file_url,
            file_name=file_name,
        )
        venture.verification_documents.append(doc)
        if venture.verification_requested and venture.verification_status in (
            VentureVerificationStatus.NONE,
            VentureVerificationStatus.REJECTED,
        ):
            venture.verification_status = VentureVerificationStatus.PENDING
        venture.updated_at = datetime.now(timezone.utc)
        await self._repo.save(venture)
        await self._session.commit()
        return await self.get_venture(venture_id)

    async def approve_verification(
        self,
        venture_id: uuid.UUID,
        *,
        admin: AppUser,
    ) -> Venture:
        from app.service.venture.venture_pitch_service import _notify_sync

        venture = await self.get_venture(venture_id)
        if not venture.verification_requested:
            raise AppException("No verification was requested for this listing.", status_code=400)
        now = datetime.now(timezone.utc)
        venture.verification_status = VentureVerificationStatus.APPROVED
        venture.verification_rejection_reason = None
        venture.verification_reviewed_at = now
        venture.verification_reviewed_by_user_id = admin.id
        venture.verified = True
        venture.verified_at = now
        venture.updated_at = now
        await self._repo.save(venture)
        await self._session.commit()
        brand_name = venture.brand_details.brand_name if venture.brand_details else "Your venture"
        if venture.listed_by_user_id:
            _notify_sync(
                venture.listed_by_user_id,
                notification_type=NotificationType.VENTURE_VERIFICATION_APPROVED,
                title="Verification Approved",
                message=f"Verification for {brand_name} was approved.",
                target_url="/ventures/dashboard",
            )
        return await self.get_venture(venture_id)

    async def reject_verification(
        self,
        venture_id: uuid.UUID,
        *,
        admin: AppUser,
        reason: str = "",
    ) -> Venture:
        from app.service.venture.venture_pitch_service import _notify_sync

        venture = await self.get_venture(venture_id)
        if not venture.verification_requested:
            raise AppException("No verification was requested for this listing.", status_code=400)
        now = datetime.now(timezone.utc)
        venture.verification_status = VentureVerificationStatus.REJECTED
        venture.verification_rejection_reason = (reason or "").strip() or None
        venture.verification_reviewed_at = now
        venture.verification_reviewed_by_user_id = admin.id
        venture.updated_at = now
        await self._repo.save(venture)
        await self._session.commit()
        brand_name = venture.brand_details.brand_name if venture.brand_details else "Your venture"
        if venture.listed_by_user_id:
            detail = (
                f" Reason: {venture.verification_rejection_reason}"
                if venture.verification_rejection_reason
                else ""
            )
            _notify_sync(
                venture.listed_by_user_id,
                notification_type=NotificationType.VENTURE_VERIFICATION_REJECTED,
                title="Verification Not Approved",
                message=f"Verification for {brand_name} was not approved.{detail}",
                target_url="/ventures/dashboard",
            )
        return await self.get_venture(venture_id)
