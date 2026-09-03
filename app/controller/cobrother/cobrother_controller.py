"""CoBrother request REST controller."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.entity.user.app_user import AppUser
from app.service.cobrother.cobrother_service import CoBrotherService

router = APIRouter(prefix="/api/v1/cobrother", tags=["CoBrother"])


class CoBrotherRespondRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    accepted: bool
    note: str = ""


async def get_cobrother_service(
    db: AsyncSession = Depends(get_async_db),
) -> CoBrotherService:
    return CoBrotherService(db)


@router.get("/requests")
async def list_my_requests(
    service: CoBrotherService = Depends(get_cobrother_service),
    current_user: AppUser = Depends(get_current_user),
) -> list[dict]:
    requests = await service.list_my_requests(current_user)
    return [
        {
            "id": str(r.id),
            "requestType": r.request_type.value,
            "entityId": str(r.entity_id),
            "status": r.status.value,
            "createdAt": r.created_at.isoformat(),
        }
        for r in requests
    ]


@router.put("/requests/{request_id}/respond")
async def respond_to_request(
    request_id: uuid.UUID,
    payload: CoBrotherRespondRequest,
    service: CoBrotherService = Depends(get_cobrother_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    updated = await service.respond(
        request_id,
        accepted=payload.accepted,
        note=payload.note,
        cobrother=current_user,
    )
    return {
        "success": True,
        "status": updated.status.value,
    }
