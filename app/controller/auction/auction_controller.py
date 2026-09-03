"""
Auction REST controller.

Mount in app/main.py:
    from app.controller.auction.auction_controller import router as auction_router
    app.include_router(auction_router)
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_async_db
from app.core.dependencies import get_current_user, require_role
from app.entity.auction.auction_entity import Auction
from app.entity.user.app_user import AppUser
from app.model.auction.auction_request import (
    CreateAuctionRequest,
    ReAuctionRequest,
)
from app.model.auction.auction_response import (
    AuctionListResponse,
    AuctionResponse,
)
from app.service.auction.auction_service import AuctionService
from app.service.auction.bid_service import BidService
from app.service.platform.platform_settings_service import PlatformSettingsService
from app.utils.enums import AuctionStatus

router = APIRouter(prefix="/api/v1/auction", tags=["Auctions"])


class ParticipationFeesUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    domain_participation_fee_inr: float | None = Field(
        None, gt=0, le=100_000, validation_alias="domainParticipationFeeInr"
    )
    software_participation_fee_inr: float | None = Field(
        None, gt=0, le=100_000, validation_alias="softwareParticipationFeeInr"
    )
    community_participation_fee_inr: float | None = Field(
        None, gt=0, le=100_000, validation_alias="communityParticipationFeeInr"
    )


async def get_auction_service(
    db: AsyncSession = Depends(get_async_db),
) -> AuctionService:
    return AuctionService(db)


async def get_bid_service(
    db: AsyncSession = Depends(get_async_db),
) -> BidService:
    return BidService(db)


async def get_settings_service(
    db: AsyncSession = Depends(get_async_db),
) -> PlatformSettingsService:
    return PlatformSettingsService(db)


@router.get("/participation-fees")
async def get_participation_fees(
    service: PlatformSettingsService = Depends(get_settings_service),
):
    return await service.get_all_participation_fees()


@router.put("/admin/participation-fees")
async def update_participation_fees(
    payload: ParticipationFeesUpdateBody,
    service: PlatformSettingsService = Depends(get_settings_service),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    try:
        return await service.update_all_participation_fees(
            domain_fee_inr=payload.domain_participation_fee_inr,
            software_fee_inr=payload.software_participation_fee_inr,
            community_fee_inr=payload.community_participation_fee_inr,
        )
    except ValueError as exc:
        from app.core.exceptions import AppException
        raise AppException(str(exc), status_code=400) from exc


@router.post(
    "/domain/{domain_id}",
    response_model=AuctionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_auction(
    domain_id: uuid.UUID,
    payload: CreateAuctionRequest,
    service: AuctionService = Depends(get_auction_service),
    current_user: AppUser = Depends(get_current_user),
) -> AuctionResponse:
    """Create a new auction for a domain owned by the current user."""
    payload = payload.model_copy(update={"domain_id": domain_id})
    auction = await service.create_auction(payload, actor=current_user)
    return AuctionResponse.model_validate(auction)


@router.post(
    "/{auction_id}/re-auction",
    response_model=AuctionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def re_auction(
    auction_id: uuid.UUID,
    payload: ReAuctionRequest,
    service: AuctionService = Depends(get_auction_service),
    current_user: AppUser = Depends(get_current_user),
) -> AuctionResponse:
    """Relist a domain whose prior auction is UNSOLD / CANCELLED / ENDED."""
    auction = await service.re_auction(
        auction_id, payload, actor=current_user
    )
    return AuctionResponse.model_validate(auction)


@router.get("/active")
async def list_active_auctions(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    service: AuctionService = Depends(get_auction_service),
) -> dict:
    items = await service.list_active_enriched(page=page, page_size=page_size)
    total = await service.count_active_auctions()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


@router.get("/my")
async def list_my_auctions(
    service: AuctionService = Depends(get_auction_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    """Domain auctions listed by the current user (Your Auctions)."""
    items = await service.list_my_auctions(current_user)
    return {"success": True, "count": len(items), "data": items, "items": items}


@router.get("/my-bids")
async def list_my_bids(
    service: AuctionService = Depends(get_auction_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    """Domain auctions the current user has bid on (Your Bids)."""
    items = await service.list_my_bids(current_user)
    return {"success": True, "count": len(items), "data": items, "items": items}


@router.get("/admin/all")
async def list_all_auctions(
    auction_status: Optional[AuctionStatus] = Query(default=None),
    service: AuctionService = Depends(get_auction_service),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
) -> dict:
    """Admin-facing listing with domain, bids, and lister (camelCase)."""
    data = await service.list_all_for_admin(status=auction_status)
    return {"success": True, "count": len(data), "data": data}


@router.get("/domain/{domain_id}", response_model=AuctionResponse)
async def get_auction_by_domain(
    domain_id: uuid.UUID,
    service: AuctionService = Depends(get_auction_service),
) -> AuctionResponse:
    """Return the most recently created auction for this domain (latest row)."""
    auction = await service.get_auction_by_domain(domain_id)
    return AuctionResponse.model_validate(auction)


@router.get(
    "/domain/{domain_id}/list",
    response_model=AuctionListResponse,
    summary="List auctions for a domain",
)
async def list_domain_auctions(
    domain_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
) -> AuctionListResponse:
    """
    All non-deleted auctions for ``domain_id``, newest first.

    Public read (no auth), aligned with ``GET /domain/{domain_id}``.
    """
    alive = Auction.is_deleted.is_(False)
    offset = max(0, (page - 1) * page_size)

    total_stmt = (
        select(func.count())
        .select_from(Auction)
        .where(Auction.domain_id == domain_id, alive)
    )
    total = int((await db.execute(total_stmt)).scalar_one() or 0)

    stmt = (
        select(Auction)
        .where(Auction.domain_id == domain_id, alive)
        .options(selectinload(Auction.bids))
        .order_by(Auction.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).scalars().all()

    return AuctionListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[AuctionResponse.model_validate(a) for a in rows],
    )


@router.get("/{auction_id}")
async def get_auction(
    auction_id: uuid.UUID,
    service: AuctionService = Depends(get_auction_service),
) -> dict:
    return await service.get_auction_detail(auction_id)


@router.post("/{auction_id}/close", response_model=AuctionResponse)
async def close_auction(
    auction_id: uuid.UUID,
    force_cancel: bool = Query(
        default=False,
        description="If true, marks the auction CANCELLED (creator/admin).",
    ),
    service: AuctionService = Depends(get_auction_service),
    current_user: AppUser = Depends(get_current_user),
) -> AuctionResponse:
    """
    Close an auction.

    - `force_cancel=false` (default): resolve to PAYMENT_PENDING / UNSOLD
      based on existing bids.
    - `force_cancel=true`: marks the auction CANCELLED (creator or admin).
    """
    auction = await service.close_auction(
        auction_id,
        actor=current_user,
        force_cancel=force_cancel,
    )
    return AuctionResponse.model_validate(auction)
