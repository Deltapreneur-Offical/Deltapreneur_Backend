"""Public operations services catalog API."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.database import get_async_db, get_db
from app.core.dependencies import get_optional_current_user
from app.entity.user.app_user import AppUser
from app.repository.operations_service_view_repository import OperationsServiceViewRepository
from app.service.analytics.viewer_metadata import viewer_analytics_metadata
from app.service.marketplace.listing_view_counter import record_operations_service_view
from app.service.operations.operations_service_service import OperationsServiceService

router = APIRouter(prefix="/api/v1/operations/services", tags=["Operations Services"])
logger = logging.getLogger(__name__)


def _get_service(db: AsyncSession = Depends(get_async_db)) -> OperationsServiceService:
    return OperationsServiceService(db)


def _attach_view_counts(db: Session, items: list[dict]) -> list[dict]:
    try:
        service_ids = [uuid.UUID(str(item["id"])) for item in items if item.get("id")]
        counts = OperationsServiceViewRepository.bulk_counts(db, service_ids)
        for item in items:
            item["views"] = counts.get(str(item["id"]), 0)
    except Exception:
        logger.exception("Failed to attach operations service view counts")
        for item in items:
            item.setdefault("views", 0)
    return items


@router.get("")
async def list_operations_services(
    service_type: str | None = Query(None, alias="serviceType"),
    service: OperationsServiceService = Depends(_get_service),
    db: Session = Depends(get_db),
) -> dict:
    normalized_type = service_type.strip().lower() if service_type else None
    if normalized_type and normalized_type not in {"virtual_assistance", "compliance"}:
        normalized_type = None
    items = await service.list_public(service_type=normalized_type)
    items = _attach_view_counts(db, items)
    return {
        "success": True,
        "message": "Operations services fetched",
        "data": items,
        "items": items,
    }


@router.get("/{service_id}")
async def get_operations_service(
    service_id: uuid.UUID,
    request: Request,
    service: OperationsServiceService = Depends(_get_service),
    db: Session = Depends(get_db),
    viewer: AppUser | None = Depends(get_optional_current_user),
) -> dict:
    try:
        industry, role = viewer_analytics_metadata(db, viewer)
        record_operations_service_view(
            db,
            service_id=service_id,
            viewer=viewer,
            client_ip=request.client.host if request.client else None,
            viewer_industry=industry,
            viewer_role=role,
        )
    except Exception:
        logger.exception(
            "Operations service view tracking failed service_id=%s",
            service_id,
        )

    item = await service.get_public(service_id)
    try:
        item["views"] = OperationsServiceViewRepository.count_by_service_id(db, service_id)
    except Exception:
        item["views"] = 0
    return {
        "success": True,
        "message": "Operations service fetched",
        "data": item,
    }
