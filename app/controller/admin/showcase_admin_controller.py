"""Admin API for the OpenProvider Premium Showcase.

All endpoints are ADMIN-only and operate purely on the showcase table +
platform_settings. OpenProvider is called ONLY by generation/select/refresh —
never by the list/config endpoints.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import require_role
from app.core.exceptions import AppException
from app.entity.user.app_user import AppUser
from app.service.domain.showcase_domain_service import (
    ShowcaseDomainService,
    get_generation_status,
    request_cancel_in_memory,
)
from app.service.domain.showcase_config_service import ShowcaseConfigService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin/showcase",
    tags=["Admin"],
)


class GenerateRequest(BaseModel):
    seed_labels: Optional[list[str]] = Field(default=None, max_length=100)
    allowed_tlds: Optional[list[str]] = Field(default=None, max_length=50)
    count: int = Field(default=50, ge=1, le=100)
    mode: Literal["keyword", "random"] = "keyword"
    # Optional client-generated id so the UI can poll /status while the POST
    # is still in flight (async server serves the poll concurrently).
    generation_id: Optional[str] = Field(default=None, min_length=1, max_length=64)


class CancelRequest(BaseModel):
    generation_id: str = Field(..., min_length=1, max_length=64)


class ConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    seed_labels: Optional[list[str]] = None
    allowed_tlds: Optional[list[str]] = None
    max_selected: Optional[int] = Field(default=None, ge=1, le=200)
    refresh_interval_hours: Optional[int] = Field(default=None, ge=1, le=168)


class SelectRequest(BaseModel):
    id: str = Field(..., description="UUID of the showcase domain row")


def _build_filters(
    search: Optional[str],
    tlds: Optional[str],
    price_min: Optional[float],
    price_max: Optional[float],
    under_5l: Optional[bool],
    over_5l: Optional[bool],
    available: Optional[bool],
    is_selected: Optional[bool],
    premium_only: Optional[bool],
    generated_since: Optional[str],
    checked_since: Optional[str],
    length_min: Optional[int],
    length_max: Optional[int],
    with_numbers: Optional[bool],
    with_hyphen: Optional[bool],
) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if search:
        filters["search"] = search
    if tlds:
        filters["tlds"] = [t.strip() for t in tlds.split(",") if t.strip()]
    if price_min is not None:
        filters["price_min"] = price_min
    if price_max is not None:
        filters["price_max"] = price_max
    if under_5l:
        filters["under_5l"] = True
    if over_5l:
        filters["over_5l"] = True
    if available is not None:
        filters["available"] = available
    if is_selected is not None:
        filters["is_selected"] = is_selected
    if premium_only:
        filters["premium_only"] = True
    for key, raw in (("generated_since", generated_since), ("checked_since", checked_since)):
        if raw:
            try:
                filters[key] = datetime.fromisoformat(raw)
            except ValueError:
                filters[key] = None
    if length_min is not None:
        filters["length_min"] = length_min
    if length_max is not None:
        filters["length_max"] = length_max
    if with_numbers:
        filters["with_numbers"] = True
    if with_hyphen:
        filters["with_hyphen"] = True
    return {k: v for k, v in filters.items() if v is not None}


@router.get("")
async def list_showcase_domains(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort: str = Query("newest"),
    search: Optional[str] = Query(None),
    tlds: Optional[str] = Query(None),
    price_min: Optional[float] = Query(None),
    price_max: Optional[float] = Query(None),
    under_5l: Optional[bool] = Query(None),
    over_5l: Optional[bool] = Query(None),
    available: Optional[bool] = Query(None),
    is_selected: Optional[bool] = Query(None),
    premium_only: Optional[bool] = Query(None),
    generated_since: Optional[str] = Query(None),
    checked_since: Optional[str] = Query(None),
    length_min: Optional[int] = Query(None),
    length_max: Optional[int] = Query(None),
    with_numbers: Optional[bool] = Query(None),
    with_hyphen: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_async_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
) -> dict[str, Any]:
    svc = ShowcaseDomainService(db)
    read_only = svc.read_only_mode() or not await svc.table_available()
    filters = _build_filters(
        search=search,
        tlds=tlds,
        price_min=price_min,
        price_max=price_max,
        under_5l=under_5l,
        over_5l=over_5l,
        available=available,
        is_selected=is_selected,
        premium_only=premium_only,
        generated_since=generated_since,
        checked_since=checked_since,
        length_min=length_min,
        length_max=length_max,
        with_numbers=with_numbers,
        with_hyphen=with_hyphen,
    )
    if read_only:
        items, total = [], 0
    else:
        items, total = await svc.list_rows(
            filters=filters, sort=sort, page=page, page_size=page_size
        )
    config = await ShowcaseConfigService(db).get()
    return {
        "success": True,
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "config": config,
        "readOnly": read_only,
        "migrationRequired": read_only,
    }


@router.post("/generate")
async def generate_candidates(
    body: GenerateRequest,
    db: AsyncSession = Depends(get_async_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
) -> dict[str, Any]:
    svc = ShowcaseDomainService(db)
    if body.mode == "random":
        result = await svc.generate_random_candidates(
            allowed_tlds=body.allowed_tlds,
            count=body.count,
            generation_id=body.generation_id,
        )
    else:
        result = await svc.generate_candidates(
            seed_labels=body.seed_labels,
            allowed_tlds=body.allowed_tlds,
            count=body.count,
            generation_id=body.generation_id,
        )
    return {"success": True, **result}


@router.get("/status")
async def generation_status(
    generation_id: str = Query(..., min_length=1),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
) -> dict[str, Any]:
    """Live progress snapshot for a running/completed generation.

    Polled by the admin UI while a Generate/Refresh request is in flight so
    the admin sees exactly what OpenProvider is doing. In-process only.
    """
    status = get_generation_status(generation_id)
    if status is None:
        raise AppException(
            "Unknown or expired generation.",
            status_code=404,
            code="SHOWCASE_STATUS_NOT_FOUND",
        )
    return {"success": True, "status": status}


@router.post("/cancel")
async def cancel_generation(
    body: CancelRequest,
    db: AsyncSession = Depends(get_async_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
) -> dict[str, Any]:
    """Stop in-flight Generate at the next label/chunk. Keeps candidates already found."""
    request_cancel_in_memory(body.generation_id)
    requested = await ShowcaseConfigService(db).request_cancel(body.generation_id)
    return {"success": True, "requested": requested}


@router.post("/select")
async def select_domain(
    body: SelectRequest,
    db: AsyncSession = Depends(get_async_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
) -> dict[str, Any]:
    svc = ShowcaseDomainService(db)
    row = await svc.select_domain(uuid.UUID(body.id))
    return {"success": True, "item": row}


@router.post("/unselect")
async def unselect_domain(
    body: SelectRequest,
    db: AsyncSession = Depends(get_async_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
) -> dict[str, Any]:
    svc = ShowcaseDomainService(db)
    row = await svc.unselect_domain(uuid.UUID(body.id))
    return {"success": True, "item": row}


@router.post("/refresh")
async def refresh_showcase(
    db: AsyncSession = Depends(get_async_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
) -> dict[str, Any]:
    svc = ShowcaseDomainService(db)
    result = await svc.refresh_selected()
    return {"success": True, **result}


@router.delete("/{row_id}")
async def remove_domain(
    row_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
) -> dict[str, Any]:
    svc = ShowcaseDomainService(db)
    await svc.remove_domain(row_id)
    return {"success": True}


@router.put("/config")
async def update_config(
    body: ConfigRequest,
    db: AsyncSession = Depends(get_async_db),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
) -> dict[str, Any]:
    # Config writes to platform_settings — refuse in read-only mode too.
    await ShowcaseDomainService(db).ensure_table()
    patch = body.model_dump(exclude_none=True)
    svc = ShowcaseConfigService(db)
    config = await svc.update(patch)
    await db.commit()
    return {"success": True, "config": config}
