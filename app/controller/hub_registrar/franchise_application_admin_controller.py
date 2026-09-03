"""Admin Franchise Application API — manage applications."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import require_role
from app.entity.user.app_user import AppUser
from app.model.hub_registrar.franchise_application_request import (
    FranchiseApplicationBlacklistRequest,
    FranchiseApplicationUpdateStatusRequest,
)
from app.service.hub_registrar.franchise_application_service import (
    FranchiseApplicationService,
)

router = APIRouter(
    prefix="/api/v1/admin/franchise-applications",
    tags=["Admin Franchise Applications"],
)


def _serialize(app) -> dict:
    return {
        "id": str(app.id),
        "full_name": app.full_name,
        "mobile_number": app.mobile_number,
        "email": app.email,
        "city": app.city,
        "state": app.state,
        "full_address": app.full_address,
        "existing_business_name": app.existing_business_name,
        "business_type": app.business_type,
        "preferred_location": app.preferred_location,
        "existing_office_availability": app.existing_office_availability,
        "relevant_experience": app.relevant_experience,
        "reason_for_applying": app.reason_for_applying,
        "additional_information": app.additional_information,
        "map_url": app.map_url,
        "status": app.status,
        "is_blacklisted": app.is_blacklisted,
        "blacklist_reason": app.blacklist_reason,
        "created_at": app.created_at.isoformat() if app.created_at else None,
        "updated_at": app.updated_at.isoformat() if app.updated_at else None,
    }


@router.get("")
async def admin_list_applications(
    status_filter: Optional[str] = None,
    search: Optional[str] = None,
    blacklisted: bool = False,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """List all franchise applications for admin."""
    applications = await FranchiseApplicationService.get_all_applications(
        db, status=status_filter, search=search, blacklisted_only=blacklisted
    )
    return {
        "success": True,
        "message": "Franchise applications fetched",
        "data": [_serialize(app) for app in applications],
    }


@router.get("/{app_id}")
async def admin_get_application(
    app_id: uuid.UUID,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Get a single franchise application."""
    application = await FranchiseApplicationService.get_application_by_id(db, app_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return {
        "success": True,
        "message": "Franchise application fetched",
        "data": _serialize(application),
    }


@router.patch("/{app_id}/status")
async def admin_update_status(
    app_id: uuid.UUID,
    body: FranchiseApplicationUpdateStatusRequest,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Update application status."""
    application = await FranchiseApplicationService.get_application_by_id(db, app_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    application = await FranchiseApplicationService.update_status(
        db, application, body.status, body.blacklist_reason
    )
    return {
        "success": True,
        "message": f"Application status updated to {body.status}",
        "data": _serialize(application),
    }


@router.post("/{app_id}/blacklist")
async def admin_blacklist_applicant(
    app_id: uuid.UUID,
    body: FranchiseApplicationBlacklistRequest,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Blacklist an applicant."""
    application = await FranchiseApplicationService.get_application_by_id(db, app_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    application = await FranchiseApplicationService.blacklist_applicant(
        db, application, body.reason
    )
    return {
        "success": True,
        "message": "Applicant has been blacklisted",
        "data": _serialize(application),
    }


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def admin_delete_application(
    app_id: uuid.UUID,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    """Permanently delete a franchise application."""
    application = await FranchiseApplicationService.get_application_by_id(db, app_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    await FranchiseApplicationService.delete_application(db, application)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
