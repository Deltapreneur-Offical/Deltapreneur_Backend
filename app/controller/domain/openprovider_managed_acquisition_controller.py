"""OpenProvider managed acquisition admin + buyer mine REST."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user, require_role
from app.entity.user.app_user import AppUser
from app.service.domain.managed_acquisition_service import ManagedAcquisitionService
from app.service.domain.openprovider_managed_acquisition_service import (
    OpenProviderManagedAcquisitionService,
)

admin_router = APIRouter(
    prefix="/api/v1/openprovider-managed-acquisitions",
    tags=["OpenProvider Managed Acquisitions"],
)
buyer_router = APIRouter(
    prefix="/api/v1/managed-acquisitions",
    tags=["Managed Acquisitions"],
)


class StatusBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    status: str
    admin_notes: str | None = Field(None, alias="adminNotes")


class RemoveBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    admin_notes: str | None = Field(None, alias="adminNotes")


async def _op_service(
    db: AsyncSession = Depends(get_async_db),
) -> OpenProviderManagedAcquisitionService:
    return OpenProviderManagedAcquisitionService(db)


async def _unified_service(
    db: AsyncSession = Depends(get_async_db),
) -> ManagedAcquisitionService:
    return ManagedAcquisitionService(db)


@admin_router.get("/all")
async def list_all_acquisitions(
    service: OpenProviderManagedAcquisitionService = Depends(_op_service),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
) -> list[dict[str, Any]]:
    return await service.list_all_admin()


@admin_router.put("/{acquisition_id}/status")
async def update_acquisition_status(
    acquisition_id: uuid.UUID,
    body: StatusBody,
    service: OpenProviderManagedAcquisitionService = Depends(_op_service),
    admin: AppUser = Depends(require_role(["ADMIN"])),
) -> dict[str, Any]:
    row = await service.update_status(
        acquisition_id,
        admin=admin,
        status=body.status,
        admin_notes=body.admin_notes,
    )
    return {"success": True, "acquisition": row}


@admin_router.post("/{acquisition_id}/remove")
async def remove_acquisition(
    acquisition_id: uuid.UUID,
    body: RemoveBody | None = None,
    service: OpenProviderManagedAcquisitionService = Depends(_op_service),
    admin: AppUser = Depends(require_role(["ADMIN"])),
) -> dict[str, Any]:
    return await service.remove(
        acquisition_id,
        admin=admin,
        admin_notes=body.admin_notes if body else None,
    )


@buyer_router.get("/mine")
async def list_my_acquisitions(
    service: ManagedAcquisitionService = Depends(_unified_service),
    current_user: AppUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return await service.list_mine(current_user.id)
