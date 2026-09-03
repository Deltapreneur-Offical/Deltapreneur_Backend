"""Co-venture (partnership) application workflows.

Co-Venture is partnership-centric: applicants apply to join a venture as a
partner / co-founder. Selecting a partner finalizes the partnership. When the
listing has a partnership fee (deal_value), a venture deal is also created for
admin approval and payment — same flow as venture sales. Free partnerships
skip payment; HubRegistrar assists both parties via support@hubregistrar.com.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.coventure.partner_entity import CoVenture
from app.entity.notification.notification_type import NotificationType
from app.entity.user.app_user import AppUser
from app.model.venture.venture_request import CoVentureApplyRequest, CoVentureStatusUpdateRequest
from app.repository.coventure_repository import CoVentureRepository
from app.repository.venture_deal_repository import VentureDealRepository
from app.repository.venture_repository import VentureRepository
from app.service.venture.venture_deal_service import VentureDealService, coventure_gross_amount_inr
from app.service.venture.venture_pitch_service import _notify_admins_sync, _notify_sync
from app.utils.venture_enums import (
    CoVentureStatus,
    VentureListingApprovalStatus,
    VentureListingMode,
    VentureListingStatus,
)


class PartnershipService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._co_repo = CoVentureRepository(session)
        self._venture_repo = VentureRepository(session)
        self._deal_repo = VentureDealRepository(session)

    async def get_my_status(
        self,
        venture_id: uuid.UUID,
        *,
        applicant: AppUser,
    ) -> dict:
        existing = await self._co_repo.find_by_venture_and_applicant(
            venture_id, applicant.id,
        )
        if existing:
            return {"applied": True, "status": existing.status.value}
        return {"applied": False}

    async def apply(
        self,
        venture_id: uuid.UUID,
        payload: CoVentureApplyRequest,
        *,
        applicant: AppUser,
    ) -> CoVenture:
        if await self._co_repo.exists_for_venture_and_applicant(venture_id, applicant.id):
            raise AppException(
                "You have already applied to this venture.",
                status_code=409,
            )

        venture = await self._venture_repo.get_by_id(venture_id, load_roles=False)
        if venture is None:
            raise AppException("Venture not found.", status_code=404)

        if venture.listed_by_user_id == applicant.id:
            raise AppException("You cannot apply to your own venture.", status_code=400)

        if not venture.status or venture.taken_down:
            raise AppException("This venture is not accepting applications.", status_code=400)
        if venture.listing_mode != VentureListingMode.CO_VENTURE:
            raise AppException(
                "This listing is not open for co-venture applications.",
                status_code=400,
            )
        if venture.listing_approval_status != VentureListingApprovalStatus.APPROVED:
            raise AppException(
                "This venture is not available for applications yet.",
                status_code=400,
            )
        if venture.venture_listing_status != VentureListingStatus.ACTIVE:
            raise AppException("This venture is no longer accepting applications.", status_code=400)

        application = CoVenture(
            venture_id=venture_id,
            applicant_user_id=applicant.id,
            full_name=payload.full_name,
            phone=payload.phone,
            location=payload.location,
            gstin=payload.gstin,
            description=payload.description,
            experience_summary=payload.experience_summary,
            skills=payload.skills,
            portfolio_url=payload.portfolio_url,
            linkedin_url=payload.linkedin_url,
            previous_ventures=payload.previous_ventures,
            relevant_experience=payload.relevant_experience,
            motivation=payload.motivation,
            contribution_plan=payload.contribution_plan,
            video_introduction_url=payload.video_introduction_url,
            status=CoVentureStatus.PENDING,
        )
        application = await self._co_repo.create(application)
        venture.co_venture_application_count += 1
        await self._venture_repo.save(venture)
        await self._session.commit()

        brand = venture.brand_details
        brand_name = brand.brand_name if brand else "your venture"
        if venture.listed_by_user_id:
            _notify_sync(
                venture.listed_by_user_id,
                notification_type=NotificationType.COVENTURE_APPLICATION_SUBMITTED,
                title="New Partnership Application",
                message=f"{payload.full_name} applied to become a partner on {brand_name}.",
                target_url="/ventures/dashboard",
            )
        _notify_admins_sync(
            notification_type=NotificationType.COVENTURE_APPLICATION_SUBMITTED,
            title="New Partnership Application",
            message=f"Partnership application received for {brand_name}.",
            target_url="/admin",
        )

        loaded = await self._co_repo.get_by_id(application.id)
        return loaded if loaded is not None else application

    async def list_my_applications(self, applicant: AppUser) -> list[CoVenture]:
        return list(await self._co_repo.list_by_applicant(applicant.id))

    async def list_venture_owner_applications(
        self,
        owner: AppUser,
        *,
        status: str | None = None,
    ) -> list[CoVenture]:
        parsed: CoVentureStatus | None = None
        if status:
            try:
                parsed = CoVentureStatus(status.upper())
            except ValueError:
                raise AppException("Invalid status value.", status_code=400)
        return list(await self._co_repo.list_by_venture_owner(owner.id, status=parsed))

    async def update_status(
        self,
        application_id: uuid.UUID,
        payload: CoVentureStatusUpdateRequest,
        *,
        owner: AppUser,
    ) -> CoVenture:
        application = await self._co_repo.get_by_id(application_id)
        if application is None:
            raise AppException("Application not found.", status_code=404)

        venture = application.venture
        if venture is None or venture.listed_by_user_id != owner.id:
            raise AppException(
                "Only the venture owner can update application status.",
                status_code=403,
            )

        try:
            new_status = CoVentureStatus(payload.status.upper())
        except ValueError:
            raise AppException("Invalid status value.", status_code=400)
        if new_status == CoVentureStatus.SELECTED:
            raise AppException(
                "Use the select-partner action to finalize a partnership.",
                status_code=400,
            )

        application.status = new_status
        application.updated_at = datetime.now(timezone.utc)
        await self._co_repo.save(application)
        await self._session.commit()

        brand = venture.brand_details
        brand_name = brand.brand_name if brand else "the venture"
        if new_status == CoVentureStatus.APPROVED:
            _notify_sync(
                application.applicant_user_id,
                notification_type=NotificationType.COVENTURE_APPLICATION_ACCEPTED,
                title="Application Under Review",
                message=f"The owner of {brand_name} is reviewing your partnership application.",
                target_url="/ventures/dashboard",
            )
        elif new_status == CoVentureStatus.REJECTED:
            _notify_sync(
                application.applicant_user_id,
                notification_type=NotificationType.COVENTURE_APPLICATION_REJECTED,
                title="Application Not Selected",
                message=f"Your partnership application for {brand_name} was not selected.",
                target_url="/ventures/dashboard",
            )
        return application

    async def select_partner(
        self,
        application_id: uuid.UUID,
        *,
        owner: AppUser,
    ) -> CoVenture:
        """Finalize a partnership with the selected applicant.

        The listing moves to PARTNERSHIP_FINALIZED. When deal_value > 0, a
        venture deal is created for admin approval and payment; free partnerships
        proceed without payment and HubRegistrar assists via support@hubregistrar.com.
        """
        application = await self._co_repo.get_by_id(application_id)
        if application is None:
            raise AppException("Application not found.", status_code=404)

        venture = application.venture
        if venture is None or venture.listed_by_user_id != owner.id:
            raise AppException(
                "Only the venture owner can select a partner.",
                status_code=403,
            )
        if venture.listing_mode != VentureListingMode.CO_VENTURE:
            raise AppException(
                "Partner selection is only available on co-venture listings.",
                status_code=400,
            )
        if application.status not in (CoVentureStatus.PENDING, CoVentureStatus.APPROVED):
            raise AppException(
                "This application cannot be selected in its current state.",
                status_code=400,
            )
        if venture.venture_listing_status not in (
            VentureListingStatus.ACTIVE,
            VentureListingStatus.PARTNERSHIP_FINALIZED,
        ):
            raise AppException("Listing is not active.", status_code=400)
        if (
            venture.selected_coventure_id is not None
            and venture.selected_coventure_id != application.id
        ):
            raise AppException(
                "A partner has already been selected for this venture.",
                status_code=409,
            )

        now = datetime.now(timezone.utc)
        application.status = CoVentureStatus.SELECTED
        application.updated_at = now
        await self._co_repo.save(application)

        venture.selected_coventure_id = application.id
        venture.venture_listing_status = VentureListingStatus.PARTNERSHIP_FINALIZED
        await self._venture_repo.save(venture)

        deal_payload = None
        deal_service = VentureDealService(self._session)
        existing_deal = await self._deal_repo.get_open_for_venture_and_buyer(
            venture.id,
            application.applicant_user_id,
        )
        if existing_deal is None:
            gross_inr = coventure_gross_amount_inr(venture)
            deal_payload = await deal_service.create_from_coventure(
                venture=venture,
                application=application,
                gross_amount_inr=gross_inr,
            )

        await self._session.commit()

        brand = venture.brand_details
        brand_name = brand.brand_name if brand else "the venture"
        deal_id = (
            deal_payload.get("id") if deal_payload else (
                str(existing_deal.id) if existing_deal else None
            )
        )
        deal_url = f"/ventures/deals/{deal_id}" if deal_id else "/ventures/dashboard"
        gross_inr = coventure_gross_amount_inr(venture)
        partner_msg = (
            f"You were selected as a partner for {brand_name}. "
            + (
                "Awaiting HubRegistrar admin approval before payment."
                if gross_inr > 0
                else "HubRegistrar will assist both parties with next steps."
            )
        )
        _notify_sync(
            application.applicant_user_id,
            notification_type=NotificationType.COVENTURE_PARTNERSHIP_FINALIZED,
            title="Partnership Confirmed",
            message=partner_msg,
            target_url=deal_url,
        )
        _notify_sync(
            owner.id,
            notification_type=NotificationType.COVENTURE_PARTNERSHIP_FINALIZED,
            title="Partnership Confirmed",
            message=(
                f"You selected {application.full_name or 'a partner'} for {brand_name}."
                + (
                    " Awaiting admin approval before the partner can pay."
                    if gross_inr > 0
                    else " HubRegistrar will assist both parties with next steps."
                )
            ),
            target_url=deal_url,
        )
        _notify_admins_sync(
            notification_type=(
                NotificationType.VENTURE_DEAL_FINALIZED
                if gross_inr > 0
                else NotificationType.COVENTURE_PARTNERSHIP_FINALIZED
            ),
            title=(
                "Co-Venture Deal Awaiting Approval"
                if gross_inr > 0
                else "Partnership Finalized"
            ),
            message=(
                f"A paid co-venture deal for {brand_name} needs admin approval."
                if gross_inr > 0
                else f"A partner was selected for {brand_name}."
            ),
            target_url="/admin?tab=venture-deals" if gross_inr > 0 else "/admin",
        )
        application._deal_id = deal_id
        return application
