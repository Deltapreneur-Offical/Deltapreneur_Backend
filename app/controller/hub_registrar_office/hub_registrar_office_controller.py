"""Public Hub Registrar Office API - view offices."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.service.hub_registrar_office.hub_registrar_office_service import (
    HubRegistrarOfficeService,
)

router = APIRouter(
    prefix="/api/v1/hub-registrar-offices",
    tags=["Hub Registrar Offices"],
)


@router.get("")
async def list_offices(
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """List all active Hub Registrar Offices."""
    offices = await HubRegistrarOfficeService.get_public_offices(db)
    data = [
        {
            "id": str(office.id),
            "phone_number": office.phone_number,
            "city": office.city,
            "full_address": office.full_address,
            "map_link": office.map_link,
            "zone": office.zone,
            "display_order": office.display_order,
            "is_active": office.is_active,
            "created_at": office.created_at.isoformat() if office.created_at else None,
            "updated_at": office.updated_at.isoformat() if office.updated_at else None,
        }
        for office in offices
    ]
    return {
        "success": True,
        "message": "Hub Registrar Offices fetched",
        "data": data,
    }


@router.get("/{office_id}")
async def get_office(
    office_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Get a single Hub Registrar Office by ID."""
    office = await HubRegistrarOfficeService.get_office_by_id(db, office_id)
    if not office:
        raise HTTPException(status_code=404, detail="Office not found")
    return {
        "success": True,
        "message": "Office fetched",
        "data": {
            "id": str(office.id),
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
