"""Venture REST controller."""

from __future__ import annotations

import logging
import uuid
from typing import Union

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.database import get_async_db, get_db
from app.core.exceptions import AppException
from app.core.dependencies import get_current_user, get_optional_current_user
from app.entity.coventure.venture_entity import Venture
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.model.venture.venture_request import (
    CompanyProfileRequest,
    CreateVentureRequest,
    GstinVerifyRequest,
    UpdateVentureRequest,
)
from app.model.venture.venture_response import (
    GstinVerifyResponse,
    PublicVentureListResponse,
    PublicVentureResponse,
    VentureListResponse,
    VentureResponse,
    serialize_owner_venture,
    serialize_public_venture,
)
from app.utils.venture_enums import VentureListingMode
from app.entity.likes.like_type import LikeType
from app.service.likes.like_service import LikeService
from app.service.analytics.viewer_metadata import viewer_analytics_metadata
from app.service.marketplace.listing_view_counter import record_venture_listing_view
from app.integrations.s3.upload_service import upload_image, upload_venture_verification_document
from app.integrations.s3.media_helpers import client_media_urls
from app.service.venture.venture_service import VentureService
from app.service.venture.verification_service import VentureVerificationService

router = APIRouter(prefix="/api/v1/venture", tags=["Venture"])
logger = logging.getLogger(__name__)

VentureDetailResponse = Union[VentureResponse, PublicVentureResponse]


async def get_venture_service(
    db: AsyncSession = Depends(get_async_db),
) -> VentureService:
    return VentureService(db)


async def get_verification_service(
    db: AsyncSession = Depends(get_async_db),
) -> VentureVerificationService:
    return VentureVerificationService(db)


def _viewer_may_see_owner_detail(
    venture: Venture,
    viewer: AppUser | None,
) -> bool:
    if viewer is None:
        return False
    if viewer.role == UserRole.ADMIN:
        return True
    return venture.listed_by_user_id == viewer.id


def serialize_venture_detail(
    venture: Venture,
    viewer: AppUser | None,
    *,
    pitch_application_count: int | None = None,
) -> VentureDetailResponse:
    """Single entry point for venture-by-id responses — public vs owner/admin."""
    if _viewer_may_see_owner_detail(venture, viewer):
        return serialize_owner_venture(
            venture,
            lister=viewer if viewer and venture.listed_by_user_id == viewer.id else None,
            pitch_application_count=pitch_application_count,
        )
    return serialize_public_venture(
        venture,
        pitch_application_count=pitch_application_count,
    )


@router.get("/all", response_model=PublicVentureListResponse)
async def list_all_ventures(
    page: int = Query(1, ge=1),
    page_size: int | None = Query(
        None,
        ge=1,
        le=200,
        description="Omit to return all listings (legacy). Set to paginate.",
    ),
    mode: VentureListingMode | None = Query(
        None,
        description="Optional filter: VENTURE or CO_VENTURE. Omit for unified marketplace (both).",
    ),
    featured_only: bool = Query(
        False,
        description="When true, return only admin-featured homepage listings.",
    ),
    include_pending: bool = Query(
        False,
        description="When true, include listings that are not yet admin-approved.",
    ),
    service: VentureService = Depends(get_venture_service),
) -> PublicVentureListResponse:
    total, items = await service.list_public_page(
        page=page,
        page_size=page_size,
        listing_mode=mode,
        featured_only=featured_only,
        include_pending=include_pending,
    )
    pitch_counts = await service.pitch_counts_for_ventures(items)
    serialized = [
        serialize_public_venture(
            v,
            pitch_application_count=pitch_counts.get(v.id, 0),
        )
        for v in items
    ]
    rows = [item.model_dump(mode="json", by_alias=True) for item in serialized]
    for row in rows:
        row.setdefault("likeCount", 0)
    return PublicVentureListResponse(
        items=[PublicVentureResponse.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size if page_size is not None else total,
    )


@router.get("/my", response_model=VentureListResponse)
async def list_my_ventures(
    service: VentureService = Depends(get_venture_service),
    current_user: AppUser = Depends(get_current_user),
) -> VentureListResponse:
    items = await service.list_my(current_user)
    return VentureListResponse(
        items=[serialize_owner_venture(v, lister=current_user) for v in items],
    )


@router.get("/my-purchases")
async def list_my_venture_purchases(
    service: VentureService = Depends(get_venture_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    items = await service.list_my_purchases(current_user)
    logger.info(
        "purchases.summary.ventures user=%s count=%s items=%s",
        current_user.id,
        len(items),
        [{"id": str(x.get("id")), "ventureId": str(x.get("ventureId") or x.get("venture_id")), "title": x.get("title") or x.get("venture", {}).get("title"), "status": x.get("status")} for x in items],
    )
    return {"success": True, "items": items, "data": items}


@router.get("/{venture_id}", response_model=VentureDetailResponse)
async def get_venture(
    venture_id: uuid.UUID,
    service: VentureService = Depends(get_venture_service),
    viewer: AppUser | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
) -> VentureDetailResponse:
    venture = await service.get_venture_for_viewer(venture_id, viewer)
    pitch_count = await service.pitch_count_for_venture(venture_id)

    if viewer is not None:
        try:
            industry, role = viewer_analytics_metadata(db, viewer)
            counted = await record_venture_listing_view(
                db,
                venture_id=venture.id,
                owner_user_id=venture.listed_by_user_id,
                viewer=viewer,
                viewer_industry=industry,
                viewer_role=role,
                increment_views=lambda: service.increment_views(venture_id),
            )
            if counted:
                venture = await service.get_venture_for_viewer(venture_id, viewer)
        except Exception:
            logger.exception(
                "Venture view tracking failed venture_id=%s viewer_id=%s",
                venture_id,
                viewer.id,
            )

    return serialize_venture_detail(
        venture,
        viewer,
        pitch_application_count=pitch_count,
    )


@router.post("/", response_model=VentureResponse, status_code=status.HTTP_201_CREATED)
async def create_venture(
    payload: CreateVentureRequest,
    service: VentureService = Depends(get_venture_service),
    current_user: AppUser = Depends(get_current_user),
) -> VentureResponse:
    venture = await service.create_venture(payload, lister=current_user)
    return serialize_owner_venture(venture, lister=current_user)


@router.put("/{venture_id}", response_model=VentureResponse)
async def update_venture(
    venture_id: uuid.UUID,
    payload: UpdateVentureRequest,
    service: VentureService = Depends(get_venture_service),
    current_user: AppUser = Depends(get_current_user),
) -> VentureResponse:
    venture = await service.update_venture(venture_id, payload, actor=current_user)
    return serialize_owner_venture(venture, lister=current_user)


@router.put("/{venture_id}/company-profile", response_model=VentureResponse)
async def upsert_company_profile(
    venture_id: uuid.UUID,
    payload: CompanyProfileRequest,
    service: VentureService = Depends(get_venture_service),
    current_user: AppUser = Depends(get_current_user),
) -> VentureResponse:
    """Owner saves a (partial) company profile; completion is computed server-side."""
    venture = await service.upsert_company_profile(
        venture_id, payload, actor=current_user,
    )
    return serialize_owner_venture(venture, lister=current_user)


@router.delete("/{venture_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_venture(
    venture_id: uuid.UUID,
    service: VentureService = Depends(get_venture_service),
    current_user: AppUser = Depends(get_current_user),
) -> Response:
    await service.delete_venture(venture_id, actor=current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{venture_id}/image")
async def upload_venture_image(
    venture_id: uuid.UUID,
    file: UploadFile = File(...),
    service: VentureService = Depends(get_venture_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    image_url = await upload_image(file=file, folder="venture-images")
    venture = await service.update_venture_image(venture_id, image_url, actor=current_user)
    media = client_media_urls(image_url)
    return {
        "success": True,
        **media,
        "ventureId": str(venture.id),
    }


@router.post("/{venture_id}/verification-documents")
async def upload_verification_document(
    venture_id: uuid.UUID,
    file: UploadFile = File(...),
    service: VentureService = Depends(get_venture_service),
    current_user: AppUser = Depends(get_current_user),
) -> VentureResponse:
    file_url = await upload_venture_verification_document(
        file=file,
        folder=f"venture-verification/{venture_id}",
    )
    venture = await service.upload_verification_document(
        venture_id,
        actor=current_user,
        file_url=file_url,
        file_name=file.filename,
    )
    return serialize_owner_venture(venture, lister=current_user)


@router.post("/{venture_id}/verify/gstin", response_model=GstinVerifyResponse)
async def verify_venture_gstin(
    venture_id: uuid.UUID,
    body: GstinVerifyRequest,
    service: VentureVerificationService = Depends(get_verification_service),
    current_user: AppUser = Depends(get_current_user),
) -> GstinVerifyResponse:
    return await service.verify_gstin_for_venture(
        venture_id,
        body.gstin,
        actor=current_user,
    )


@router.post("/admin/{venture_id}/verify-gstin", response_model=GstinVerifyResponse)
async def admin_verify_venture_gstin(
    venture_id: uuid.UUID,
    body: GstinVerifyRequest,
    service: VentureVerificationService = Depends(get_verification_service),
    current_user: AppUser = Depends(get_current_user),
) -> GstinVerifyResponse:
    if current_user.role != UserRole.ADMIN:
        raise AppException("Admin access required.", status_code=403)
    return await service.verify_gstin_as_admin(venture_id, body.gstin)
