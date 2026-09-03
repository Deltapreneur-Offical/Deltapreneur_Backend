"""Technology (software) REST controller."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.database import get_async_db, get_db as get_sync_db
from app.core.dependencies import get_current_user
from app.entity.user.app_user import AppUser
from app.model.cocreation.cocreation_request import CreateSoftwareRequest, UpdateSoftwareRequest
from app.model.cocreation.cocreation_response import SoftwareResponse
from app.model.cocreation.software_mapper import build_software_response
from app.repository.software_auction_repository import SoftwareAuctionRepository
from app.repository.software_purchase_repository import SoftwarePurchaseRepository
from app.integrations.s3.upload_service import upload_image
from app.service.cocreation.cocreation_service import CocreationService
from app.service.analytics.viewer_metadata import viewer_analytics_metadata
from app.service.marketplace.listing_view_counter import record_software_listing_view
from app.model.common.api_response import ApiResponse
from app.model.common.payment_request import RazorpayVerifyRequest
from app.service.cocreation.cocreation_payment_service import CocreationPaymentService

router = APIRouter(tags=["Technology"])
logger = logging.getLogger(__name__)


# Backward-compatible alias for older tests that override the sync dependency.
get_db = get_sync_db


def _serialize_software_list(
    items: list,
    *,
    message: str,
    is_owner: bool = False,
    hide_github_from_public: bool = False,
    purchase_counts: dict | None = None,
    auctions_by_software: dict | None = None,
) -> dict:
    """Frontend expects { success, data: [...] } (also keeps items for asArray)."""
    purchase_counts = purchase_counts or {}
    auctions_by_software = auctions_by_software or {}
    rows = []
    for software in items:
        count = purchase_counts.get(software.id, 0)
        row = build_software_response(
            software,
            is_owner=is_owner,
            hide_github_from_public=hide_github_from_public,
            purchase_count=count,
        ).model_dump(mode="json", by_alias=True)
        auction = auctions_by_software.get(software.id)
        if auction is not None:
            row["auctionId"] = str(auction.id)
            row["auctionApprovalStatus"] = (
                auction.approval_status.value
                if hasattr(auction.approval_status, "value")
                else auction.approval_status
            )
            row["auctionStatus"] = (
                auction.status.value
                if hasattr(auction.status, "value")
                else auction.status
            )
        rows.append(row)
    return {
        "success": True,
        "message": message,
        "data": rows,
        "items": rows,
    }


async def get_cocreation_service(
    db: AsyncSession = Depends(get_async_db),
) -> CocreationService:
    return CocreationService(db)


async def get_payment_service(
    db: AsyncSession = Depends(get_async_db),
) -> CocreationPaymentService:
    return CocreationPaymentService(db)


async def get_purchase_repo(
    db: AsyncSession = Depends(get_async_db),
) -> SoftwarePurchaseRepository:
    return SoftwarePurchaseRepository(db)


async def get_auction_repo(
    db: AsyncSession = Depends(get_async_db),
) -> SoftwareAuctionRepository:
    return SoftwareAuctionRepository(db)


@router.get("/all")
async def list_all_software(
    page: int = Query(1, ge=1),
    page_size: int | None = Query(
        None,
        ge=1,
        le=200,
        description="Omit to return all listings (legacy). Set to paginate.",
    ),
    featured_only: bool = Query(
        False,
        description="When true, return only admin-featured homepage listings.",
    ),
    service: CocreationService = Depends(get_cocreation_service),
    auction_repo: SoftwareAuctionRepository = Depends(get_auction_repo),
) -> dict:
    total, item_list = await service.list_public_page(
        page=page,
        page_size=page_size,
        featured_only=featured_only,
    )
    auctions_by_software = await auction_repo.map_by_software_ids(
        [s.id for s in item_list],
    )
    payload = _serialize_software_list(
        item_list,
        message="Software listings fetched successfully",
        hide_github_from_public=True,
        auctions_by_software=auctions_by_software,
    )
    for row in payload["data"]:
        row.setdefault("likeCount", 0)
    payload["total"] = total
    payload["page"] = page
    payload["page_size"] = page_size if page_size is not None else total
    return payload


@router.get("/my")
async def list_my_software(
    service: CocreationService = Depends(get_cocreation_service),
    current_user: AppUser = Depends(get_current_user),
    purchase_repo: SoftwarePurchaseRepository = Depends(get_purchase_repo),
    auction_repo: SoftwareAuctionRepository = Depends(get_auction_repo),
) -> dict:
    items = await service.list_my(current_user)
    item_list = list(items)
    purchase_counts = await purchase_repo.count_completed_by_software_ids(
        [s.id for s in item_list],
    )
    auctions_by_software = await auction_repo.map_by_software_ids(
        [s.id for s in item_list],
    )
    return _serialize_software_list(
        item_list,
        message="Your software listings fetched successfully",
        is_owner=True,
        purchase_counts=purchase_counts,
        auctions_by_software=auctions_by_software,
    )


@router.get("/{software_id}", response_model=SoftwareResponse)
async def get_software(
    software_id: uuid.UUID,
    service: CocreationService = Depends(get_cocreation_service),
    current_user: AppUser = Depends(get_current_user),
    purchase_repo: SoftwarePurchaseRepository = Depends(get_purchase_repo),
    db: Session = Depends(get_db),
) -> SoftwareResponse:
    software = await service.get_software(software_id)
    is_owner = software.listed_by_user_id == current_user.id

    if not is_owner:
        try:
            industry, role = viewer_analytics_metadata(db, current_user)
            counted = await record_software_listing_view(
                db,
                software_id=software.id,
                owner_user_id=software.listed_by_user_id,
                viewer=current_user,
                viewer_industry=industry,
                viewer_role=role,
                increment_views=lambda: service.increment_views(software_id),
            )
            if counted:
                software = await service.get_software(software_id)
        except Exception:
            logger.exception(
                "Technology listing view tracking failed software_id=%s viewer_id=%s",
                software_id,
                current_user.id,
            )

    viewer_purchase = None
    if not is_owner:
        viewer_purchase = await purchase_repo.get_completed_for_buyer(
            software_id, current_user.id
        )
    return build_software_response(
        software,
        viewer_purchase=viewer_purchase,
        is_owner=is_owner,
        hide_github_from_public=not is_owner,
    )


@router.post("", response_model=SoftwareResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=SoftwareResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_software(
    payload: CreateSoftwareRequest,
    service: CocreationService = Depends(get_cocreation_service),
    current_user: AppUser = Depends(get_current_user),
) -> SoftwareResponse:
    software = await service.create_software(payload, lister=current_user)
    return build_software_response(software, is_owner=True)


@router.put("/{software_id}", response_model=SoftwareResponse)
async def update_software(
    software_id: uuid.UUID,
    payload: UpdateSoftwareRequest,
    service: CocreationService = Depends(get_cocreation_service),
    current_user: AppUser = Depends(get_current_user),
) -> SoftwareResponse:
    software = await service.update_software(software_id, payload, actor=current_user)
    return build_software_response(software, is_owner=True)


@router.post("/{software_id}/purchase/create-order")
async def create_software_purchase_order(
    software_id: uuid.UUID,
    body: dict | None = None,
    service: CocreationPaymentService = Depends(get_payment_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.create_purchase_order(
        software_id,
        buyer=current_user,
        co_brother_opt_in=bool(body.get("coBrotherOptIn")),
        buyer_full_name=str(body.get("buyerFullName", "")),
        buyer_email=str(body.get("buyerEmail", "")),
        buyer_phone=str(body.get("buyerPhone", "")),
        addon_amount=float(body.get("addonAmount", 0) or 0),
        addon_services=body.get("services"),
        selected_plan_duration=body.get("selectedPlan"),
        currency=str(body.get("currency", "INR")),
    )


@router.post("/{software_id}/purchase/verify")
async def verify_software_purchase(
    software_id: uuid.UUID,
    body: RazorpayVerifyRequest,
    service: CocreationPaymentService = Depends(get_payment_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.verify_payment(
        software_id,
        razorpay_payment_id=body.razorpay_payment_id,
        razorpay_order_id=body.razorpay_order_id,
        razorpay_signature=body.razorpay_signature,
        buyer=current_user,
    )


@router.post("/purchase/{purchase_id}/confirm")
async def confirm_software_purchase(
    purchase_id: uuid.UUID,
    service: CocreationPaymentService = Depends(get_payment_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.confirm_purchase(purchase_id, buyer=current_user)


@router.post("/{software_id}/purchase/failure")
async def software_purchase_failure(
    software_id: uuid.UUID,
    service: CocreationPaymentService = Depends(get_payment_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.handle_failure(software_id, buyer=current_user)


@router.get("/{software_id}/analytics")
async def get_software_analytics(
    software_id: uuid.UUID,
    service: CocreationService = Depends(get_cocreation_service),
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return metrics at the top level — frontend reads totalRevenue, totalViews, etc. directly."""
    payload = await service.get_analytics(
        software_id,
        actor=current_user,
        db=db,
    )
    return {
        "success": True,
        "message": "Software analytics fetched successfully",
        **payload,
    }


@router.post("/purchase/{purchase_id}/cobrother-help/create-order")
async def create_cobrother_help_order(
    purchase_id: uuid.UUID,
    service: CocreationPaymentService = Depends(get_payment_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.create_cobrother_help_order(purchase_id, buyer=current_user)


@router.post("/purchase/{purchase_id}/cobrother-help/verify")
async def verify_cobrother_help(
    purchase_id: uuid.UUID,
    body: RazorpayVerifyRequest,
    service: CocreationPaymentService = Depends(get_payment_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.verify_cobrother_help(
        purchase_id,
        razorpay_payment_id=body.razorpay_payment_id,
        razorpay_order_id=body.razorpay_order_id,
        razorpay_signature=body.razorpay_signature,
        buyer=current_user,
    )


@router.post("/{software_id}/image", response_model=SoftwareResponse)
async def upload_software_image(
    software_id: uuid.UUID,
    file: UploadFile = File(...),
    service: CocreationService = Depends(get_cocreation_service),
    current_user: AppUser = Depends(get_current_user),
) -> SoftwareResponse:
    url = await upload_image(file, folder="software-listings")
    software = await service.set_software_image_url(software_id, actor=current_user, image_url=url)
    return build_software_response(software, is_owner=True)


@router.delete(
    "/{software_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_software(
    software_id: uuid.UUID,
    service: CocreationService = Depends(get_cocreation_service),
    current_user: AppUser = Depends(get_current_user),
) -> Response:
    await service.delete_software(software_id, actor=current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
