"""Admin Hub Registrar Office API - manage offices."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import require_role
from app.entity.user.app_user import AppUser
from app.model.hub_registrar_office.hub_registrar_office_request import (
    HubRegistrarOfficeCreateRequest,
    HubRegistrarOfficeUpdateRequest,
)
from app.service.hub_registrar_office.hub_registrar_office_service import (
    HubRegistrarOfficeService,
)

router = APIRouter(
    prefix="/api/v1/admin/hub-registrar-offices",
    tags=["Admin Hub Registrar Offices"],
)


@router.get("")
async def admin_list_offices(
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """List all offices for admin."""
    offices = await HubRegistrarOfficeService.get_all_offices_admin(db, include_deleted=False)
    data = [
        {
            "id": str(office.id),
            "office_name": office.office_name,
            "phone_number": office.phone_number,
            "city": office.city,
            "full_address": office.full_address,
            "map_link": office.map_link,
            "zone": office.zone,
            "display_order": office.display_order,
            "is_active": office.is_active,
            "created_at": office.created_at.isoformat() if office.created_at else None,
            "updated_at": office.updated_at.isoformat() if office.updated_at else None,
            "is_deleted": office.is_deleted,
            "deleted_at": office.deleted_at.isoformat() if office.deleted_at else None,
            "deleted_by": str(office.deleted_by) if office.deleted_by else None,
        }
        for office in offices
    ]
    return {
        "success": True,
        "message": "Hub Registrar Offices fetched",
        "data": data,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def admin_create_office(
    body: HubRegistrarOfficeCreateRequest,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Create a new office."""
    try:
        office = await HubRegistrarOfficeService.create_office(db, body)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {
        "success": True,
        "message": "Office created successfully",
        "data": {
            "id": str(office.id),
            "office_name": office.office_name,
            "phone_number": office.phone_number,
            "city": office.city,
            "full_address": office.full_address,
            "map_link": office.map_link,
            "zone": office.zone,
            "display_order": office.display_order,
            "is_active": office.is_active,
            "created_at": office.created_at.isoformat() if office.created_at else None,
            "updated_at": office.updated_at.isoformat() if office.updated_at else None,
        },
    }


@router.put("/{office_id}")
async def admin_update_office(
    office_id: uuid.UUID,
    body: HubRegistrarOfficeUpdateRequest,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Update an existing office."""
    office = await HubRegistrarOfficeService.get_office_by_id(db, office_id)
    if not office:
        raise HTTPException(status_code=404, detail="Office not found")
    try:
        office = await HubRegistrarOfficeService.update_office(db, office, body)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {
        "success": True,
        "message": "Office updated successfully",
        "data": {
            "id": str(office.id),
            "office_name": office.office_name,
            "phone_number": office.phone_number,
            "city": office.city,
            "full_address": office.full_address,
            "map_link": office.map_link,
            "zone": office.zone,
            "display_order": office.display_order,
            "is_active": office.is_active,
            "created_at": office.created_at.isoformat() if office.created_at else None,
            "updated_at": office.updated_at.isoformat() if office.updated_at else None,
        },
    }


@router.patch("/{office_id}/active")
async def admin_toggle_office_active(
    office_id: uuid.UUID,
    is_active: bool = True,
    _admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Toggle active status of an office."""
    office = await HubRegistrarOfficeService.get_office_by_id(db, office_id)
    if not office:
        raise HTTPException(status_code=404, detail="Office not found")
    office = await HubRegistrarOfficeService.toggle_active(db, office, is_active)
    return {
        "success": True,
        "message": f"Office {'activated' if is_active else 'deactivated'} successfully",
        "data": {
            "id": str(office.id),
            "is_active": office.is_active,
        },
    }


@router.delete("/{office_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def admin_delete_office(
    office_id: uuid.UUID,
    admin: AppUser = Depends(require_role(["ADMIN"])),
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    """Soft-delete an office."""
    office = await HubRegistrarOfficeService.get_office_by_id(db, office_id)
    if not office:
        raise HTTPException(status_code=404, detail="Office not found")
    await HubRegistrarOfficeService.soft_delete(db, office, deleted_by=admin.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
