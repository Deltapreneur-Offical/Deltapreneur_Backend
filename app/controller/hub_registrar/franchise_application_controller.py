"""Franchise Application public API — submit application."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.model.hub_registrar.franchise_application_request import (
    FranchiseApplicationSubmitRequest,
)
from app.service.hub_registrar.franchise_application_service import (
    FranchiseApplicationService,
)

router = APIRouter(
    prefix="/api/v1/franchise",
    tags=["Franchise Applications"],
)


@router.post("/apply", status_code=status.HTTP_201_CREATED)
async def submit_franchise_application(
    body: FranchiseApplicationSubmitRequest,
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Submit a new franchise application (public, no auth required)."""
    try:
        application = await FranchiseApplicationService.submit_application(db, body)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {
        "success": True,
        "message": "Application submitted successfully. Our team will contact you soon.",
        "data": {"id": str(application.id)},
    }
