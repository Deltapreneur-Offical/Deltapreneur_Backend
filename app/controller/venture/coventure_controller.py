"""Co-venture (partnership application) REST controller."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.entity.user.app_user import AppUser
from app.model.venture.venture_request import CoVentureApplyRequest, CoVentureStatusUpdateRequest
from app.model.venture.venture_response import (
    CoVentureResponse,
    CoVentureStatusResponse,
    CoVentureVentureBrandSummary,
    CoVentureVentureSummary,
)
from app.utils.equity_percent import normalize_equity_percent
from app.service.venture.partnership_service import PartnershipService
from app.integrations.s3.supabase_storage import resolve_media_url

router = APIRouter(prefix="/api/v1/coventure", tags=["CoVenture"])


def _venture_summary(app) -> CoVentureVentureSummary | None:
    venture = getattr(app, "venture", None)
    if venture is None:
        return None
    brand = getattr(venture, "brand_details", None)
    brand_summary = None
    if brand is not None:
        brand_summary = CoVentureVentureBrandSummary(
            brand_name=brand.brand_name,
            industry=brand.industry,
            venture_type=brand.venture_type,
            equity_percent_offered=normalize_equity_percent(venture.equity_percent_offered),
            venture_image_url=resolve_media_url(brand.venture_image_url),
        )
    return CoVentureVentureSummary(id=venture.id, brand_details=brand_summary)


def _coventure_response(app) -> CoVentureResponse:
    """Build response without model_validate(app) — loaded ORM `venture` breaks nested schema."""
    status = app.status.value if hasattr(app.status, "value") else str(app.status)
    return CoVentureResponse(
        id=app.id,
        venture_id=app.venture_id,
        applicant_user_id=app.applicant_user_id,
        full_name=app.full_name,
        phone=app.phone,
        location=app.location,
        gstin=getattr(app, "gstin", None),
        description=app.description,
        experience_summary=getattr(app, "experience_summary", None),
        skills=getattr(app, "skills", None),
        portfolio_url=getattr(app, "portfolio_url", None),
        linkedin_url=getattr(app, "linkedin_url", None),
        previous_ventures=getattr(app, "previous_ventures", None),
        relevant_experience=getattr(app, "relevant_experience", None),
        motivation=getattr(app, "motivation", None),
        contribution_plan=getattr(app, "contribution_plan", None),
        status=status,
        created_at=app.created_at,
        updated_at=app.updated_at,
        venture=_venture_summary(app),
    )


async def get_partnership_service(
    db: AsyncSession = Depends(get_async_db),
) -> PartnershipService:
    return PartnershipService(db)


@router.get("/my-applications")
async def my_applications(
    service: PartnershipService = Depends(get_partnership_service),
    current_user: AppUser = Depends(get_current_user),
) -> list[CoVentureResponse]:
    apps = await service.list_my_applications(current_user)
    return [_coventure_response(a) for a in apps]


@router.get("/my-venture-applications")
async def my_venture_applications(
    status: str | None = Query(None),
    service: PartnershipService = Depends(get_partnership_service),
    current_user: AppUser = Depends(get_current_user),
) -> list[CoVentureResponse]:
    apps = await service.list_venture_owner_applications(current_user, status=status)
    return [_coventure_response(a) for a in apps]


@router.get("/{venture_id}/my-status", response_model=CoVentureStatusResponse)
async def my_application_status(
    venture_id: uuid.UUID,
    service: PartnershipService = Depends(get_partnership_service),
    current_user: AppUser = Depends(get_current_user),
) -> CoVentureStatusResponse:
    data = await service.get_my_status(venture_id, applicant=current_user)
    return CoVentureStatusResponse(**data)


@router.post("/{venture_id}", response_model=CoVentureResponse, status_code=201)
async def apply_to_coventure(
    venture_id: uuid.UUID,
    payload: CoVentureApplyRequest,
    service: PartnershipService = Depends(get_partnership_service),
    current_user: AppUser = Depends(get_current_user),
) -> CoVentureResponse:
    app = await service.apply(venture_id, payload, applicant=current_user)
    return _coventure_response(app)


@router.put("/{application_id}/status")
async def update_application_status(
    application_id: uuid.UUID,
    payload: CoVentureStatusUpdateRequest,
    service: PartnershipService = Depends(get_partnership_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    app = await service.update_status(application_id, payload, owner=current_user)
    return {"success": True, "status": app.status.value}


@router.post("/{application_id}/select-partner")
async def select_partner(
    application_id: uuid.UUID,
    service: PartnershipService = Depends(get_partnership_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    """Finalize a partnership with this applicant.

    Sets PARTNERSHIP_FINALIZED. When the listing has a partnership fee, also
    creates a venture deal for admin approval and payment (see dealId).
    """
    app = await service.select_partner(application_id, owner=current_user)
    deal_id = getattr(app, "_deal_id", None)
    return {
        "success": True,
        "status": app.status.value,
        "ventureId": str(app.venture_id),
        "partnershipFinalized": True,
        "dealId": deal_id,
    }
