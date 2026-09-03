"""Aliases for frontend cocreation paths that mirror /my until purchases are split."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.entity.user.app_user import AppUser
from app.model.common.api_response import ApiResponse
from app.controller.cocreation.cocreation_controller import (
    _serialize_software_list,
    get_auction_repo,
)
from app.repository.software_auction_repository import SoftwareAuctionRepository
from app.repository.software_purchase_repository import SoftwarePurchaseRepository
from app.service.cocreation.cocreation_service import CocreationService

router = APIRouter(tags=["Technology"])
logger = logging.getLogger(__name__)


async def get_cocreation_service(
    db: AsyncSession = Depends(get_async_db),
) -> CocreationService:
    return CocreationService(db)


async def get_purchase_repo(
    db: AsyncSession = Depends(get_async_db),
) -> SoftwarePurchaseRepository:
    return SoftwarePurchaseRepository(db)


@router.get("/my-listings")
async def my_cocreation_listings(
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


@router.get("/my-purchases", response_model=ApiResponse)
async def my_cocreation_purchases(
    service: CocreationService = Depends(get_cocreation_service),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResponse:
    items = await service.list_my_purchases(current_user)
    logger.info(
        "purchases.summary.technology user=%s count=%s items=%s",
        current_user.id,
        len(items),
        [{"id": str(x.get("id")), "softwareId": str(x.get("software", {}).get("id")), "softwareName": x.get("software", {}).get("name"), "paymentStatus": x.get("paymentStatus"), "completionStatus": x.get("completionStatus")} for x in items],
    )
    return ApiResponse(
        success=True,
        message="Purchases fetched successfully",
        data=items,
    )


@router.get("/my-sales", response_model=ApiResponse)
async def my_cocreation_sales(
    service: CocreationService = Depends(get_cocreation_service),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResponse:
    items = await service.list_my_sales(current_user)
    return ApiResponse(
        success=True,
        message="Sales fetched successfully",
        data=items,
    )

