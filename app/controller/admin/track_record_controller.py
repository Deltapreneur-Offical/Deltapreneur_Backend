"""Admin API Controller for Track Records module."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import require_role
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.service.platform.track_record_service import TrackRecordService

router = APIRouter(prefix="/api/v1/admin/track-records", tags=["Admin Track Records"])


@router.get("", response_model=dict)
async def get_track_records(
    start_date: Optional[str] = Query(None, description="ISO format start date"),
    end_date: Optional[str] = Query(None, description="ISO format end date"),
    category: Optional[str] = Query(None, description="Category filter"),
    overall_status: Optional[str] = Query(None, alias="overallStatus", description="Overall status filter"),
    status_param: Optional[str] = Query(None, alias="status", description="Alias for overall status filter"),
    search: Optional[str] = Query(None, description="Multi-field search term"),
    sort_by: str = Query("timestamp", alias="sortBy", description="Sort field"),
    sort_dir: str = Query("desc", alias="sortDir", description="Sort direction: asc or desc"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_async_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN"])),
):
    """List track records with filtering, searching, sorting, and pagination (Admin only)."""
    parsed_start: Optional[datetime] = None
    parsed_end: Optional[datetime] = None

    if start_date and start_date.strip():
        try:
            parsed_start = datetime.fromisoformat(start_date.strip().replace("Z", "+00:00"))
        except ValueError:
            pass

    if end_date and end_date.strip():
        try:
            parsed_end = datetime.fromisoformat(end_date.strip().replace("Z", "+00:00"))
        except ValueError:
            pass

    effective_status = overall_status or status_param

    service = TrackRecordService(db)

    records, total_count = await service.list_admin_records(
        start_date=parsed_start,
        end_date=parsed_end,
        category=category,
        overall_status=effective_status,
        search_term=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        limit=limit,
    )

    total_pages = (total_count + limit - 1) // limit if limit > 0 else 1

    items_serialized = await service.enrich_records_with_tax_invoices(records)
    return {
        "success": True,
        "items": items_serialized,
        "records": items_serialized,
        "totalCount": total_count,
        "total": total_count,
        "page": page,
        "limit": limit,
        "totalPages": total_pages,
    }


@router.get("/{record_id}", response_model=dict)
async def get_track_record_detail(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN"])),
):
    """Get full details of a specific Track Record (Admin only)."""
    service = TrackRecordService(db)
    record = await service.get_by_id(record_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track Record not found",
        )

    enriched = await service.enrich_records_with_tax_invoices([record])
    return {
        "success": True,
        "record": enriched[0] if enriched else record.to_dict(),
    }


@router.post("/sync", response_model=dict)
async def sync_track_records(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_db),
    current_user: AppUser = Depends(require_role(["ADMIN", "SUPER_ADMIN"])),
):
    """Backfill track records from domain orders and recent Razorpay payments (Admin only).

    Runs as a background task: the admin page must never block on the full
    historical backfill (it scans every order/purchase table and talks to
    Razorpay). The response returns immediately; newly synced records appear
    on the next list request / refresh.
    """
    service = TrackRecordService(db)
    background_tasks.add_task(service.sync_historical_purchases)
    return {
        "success": True,
        "scheduled": True,
        "syncedCount": 0,
    }
