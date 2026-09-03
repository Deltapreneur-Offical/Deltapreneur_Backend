"""Venture pitch REST controller."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user, require_role
from app.entity.user.app_user import AppUser
from app.service.venture.venture_pitch_service import VenturePitchService

router = APIRouter(prefix="/api/v1/venture-pitches", tags=["Venture Pitches"])


class PitchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offered_amount: float = Field(..., gt=0, alias="offeredAmount")
    requested_equity_percent: float = Field(
        ..., gt=0, le=100, alias="requestedEquityPercent",
    )
    message: str | None = Field(None, min_length=1)
    investment_proposal: str | None = Field(None, min_length=1, alias="investmentProposal")
    additional_notes: str | None = Field(None, max_length=5000, alias="additionalNotes")

    @model_validator(mode="after")
    def _require_message(self) -> "PitchBody":
        if not (self.message or self.investment_proposal or "").strip():
            raise ValueError("Message is required.")
        return self


class FinalizeDealBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pitch_id: uuid.UUID = Field(..., alias="pitchId")


async def get_service(db: AsyncSession = Depends(get_async_db)) -> VenturePitchService:
    return VenturePitchService(db)


@router.post("/venture/{venture_id}")
async def submit_pitch(
    venture_id: uuid.UUID,
    payload: PitchBody,
    service: VenturePitchService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.submit_pitch(
        venture_id,
        buyer=current_user,
        offered_amount=payload.offered_amount,
        requested_equity_percent=payload.requested_equity_percent,
        message=(payload.message or payload.investment_proposal or "").strip(),
        additional_notes=payload.additional_notes,
        investment_proposal=payload.investment_proposal,
    )


@router.get("/venture/{venture_id}/public-bids")
async def list_public_bids(
    venture_id: uuid.UUID,
    service: VenturePitchService = Depends(get_service),
):
    return await service.list_public_bids(venture_id)


@router.get("/my")
async def list_my_pitches(
    service: VenturePitchService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.list_my_pitches(current_user)


@router.get("/received")
async def list_received_pitches(
    service: VenturePitchService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.list_received(current_user)


@router.get("/admin/all")
async def admin_list_pitches(
    service: VenturePitchService = Depends(get_service),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await service.list_all_admin()


@router.get("/{pitch_id}")
async def get_pitch(
    pitch_id: uuid.UUID,
    service: VenturePitchService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.get_pitch(pitch_id, current_user)


@router.post("/{pitch_id}/seller/accept")
async def seller_accept(
    pitch_id: uuid.UUID,
    service: VenturePitchService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.seller_accept(pitch_id, seller=current_user)


@router.post("/{pitch_id}/seller/reject")
async def seller_reject(
    pitch_id: uuid.UUID,
    service: VenturePitchService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.seller_reject(pitch_id, seller=current_user)


@router.post("/{pitch_id}/seller/shortlist")
async def seller_shortlist(
    pitch_id: uuid.UUID,
    service: VenturePitchService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.seller_shortlist(pitch_id, seller=current_user)


@router.post("/{pitch_id}/cancel")
async def buyer_withdraw(
    pitch_id: uuid.UUID,
    service: VenturePitchService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.buyer_withdraw(pitch_id, buyer=current_user)


@router.post("/venture/{venture_id}/finalize-deal")
async def finalize_deal(
    venture_id: uuid.UUID,
    payload: FinalizeDealBody,
    service: VenturePitchService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.finalize_deal(
        venture_id, payload.pitch_id, seller=current_user,
    )


@router.post("/venture/{venture_id}/close")
async def close_listing(
    venture_id: uuid.UUID,
    service: VenturePitchService = Depends(get_service),
    current_user: AppUser = Depends(get_current_user),
):
    return await service.close_listing(venture_id, actor=current_user)


@router.post("/admin/venture/{venture_id}/close")
async def admin_close_listing(
    venture_id: uuid.UUID,
    service: VenturePitchService = Depends(get_service),
    admin: AppUser = Depends(require_role(["ADMIN"])),
):
    return await service.close_listing(venture_id, actor=admin, admin=True)
