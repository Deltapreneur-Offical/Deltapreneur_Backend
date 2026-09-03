"""Domain enquiry REST."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user, require_role
from app.entity.user.app_user import AppUser
from app.service.domain.domain_enquiry_service import DomainEnquiryService

router = APIRouter(prefix="/api/v1/domain-enquiry", tags=["Domain Enquiry"])


class DomainEnquirySubmitBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    full_name: str | None = Field(None, alias="fullName")
    email: str | None = None
    phone: str | None = None
    message: str | None = None


class DomainEnquiryStatusBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    status: str
    admin_notes: str | None = Field(None, alias="adminNotes")


class DomainEnquiryRemoveBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    admin_notes: str | None = Field(None, alias="adminNotes")


async def get_enquiry_service(db: AsyncSession = Depends(get_async_db)) -> DomainEnquiryService:
    return DomainEnquiryService(db)


@router.post("/{domain_id}")
async def submit_enquiry(
    domain_id: uuid.UUID,
    body: DomainEnquirySubmitBody,
    service: DomainEnquiryService = Depends(get_enquiry_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    return await service.submit(
        domain_id,
        enquirer=current_user,
        full_name=body.full_name,
        email=body.email,
        phone=body.phone,
        message=body.message,
    )


@router.get("/all")
async def list_all_enquiries(
    service: DomainEnquiryService = Depends(get_enquiry_service),
    _admin: AppUser = Depends(require_role(["ADMIN"])),
) -> list[dict[str, Any]]:
    return await service.list_all_admin()


@router.put("/{enquiry_id}/status")
async def update_enquiry_status(
    enquiry_id: uuid.UUID,
    body: DomainEnquiryStatusBody,
    service: DomainEnquiryService = Depends(get_enquiry_service),
    admin: AppUser = Depends(require_role(["ADMIN"])),
) -> dict[str, Any]:
    enquiry = await service.update_status(
        enquiry_id,
        admin=admin,
        status=body.status,
        admin_notes=body.admin_notes,
    )
    return {"success": True, "enquiry": enquiry}


@router.post("/{enquiry_id}/mark-sold")
async def mark_enquiry_domain_sold(
    enquiry_id: uuid.UUID,
    body: DomainEnquiryStatusBody | None = None,
    service: DomainEnquiryService = Depends(get_enquiry_service),
    admin: AppUser = Depends(require_role(["ADMIN"])),
) -> dict[str, Any]:
    """Separate admin action: ACCEPTED → COMPLETED and listing UNDER_REVIEW → SOLD."""
    enquiry = await service.mark_sold(
        enquiry_id,
        admin=admin,
        admin_notes=body.admin_notes if body else None,
    )
    return {"success": True, "enquiry": enquiry}


@router.post("/{enquiry_id}/remove")
async def remove_enquiry(
    enquiry_id: uuid.UUID,
    body: DomainEnquiryRemoveBody | None = None,
    service: DomainEnquiryService = Depends(get_enquiry_service),
    admin: AppUser = Depends(require_role(["ADMIN"])),
) -> dict[str, Any]:
    return await service.remove_enquiry(
        enquiry_id,
        admin=admin,
        admin_notes=body.admin_notes if body else None,
    )
