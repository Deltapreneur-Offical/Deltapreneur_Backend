"""Hub Registrar Office request/response models."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class HubRegistrarOfficeCreateRequest(BaseModel):
    """Admin create request."""
    office_name: str = Field(..., max_length=255)
    phone_number: str = Field(..., max_length=20)
    city: str = Field("", max_length=100)
    full_address: str
    map_link: Optional[str] = Field(None, max_length=500)
    zone: int = Field(0, ge=0)
    display_order: int = Field(0, ge=0)
    is_active: bool = True


class HubRegistrarOfficeUpdateRequest(BaseModel):
    """Admin update request."""
    office_name: Optional[str] = Field(None, max_length=255)
    phone_number: Optional[str] = Field(None, max_length=20)
    city: Optional[str] = Field(None, max_length=100)
    full_address: Optional[str] = None
    map_link: Optional[str] = Field(None, max_length=500)
    zone: Optional[int] = Field(None, ge=0)
    display_order: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None


class HubRegistrarOfficeResponse(BaseModel):
    """Public response model."""
    id: UUID
    office_name: str
    phone_number: str
    city: str
    full_address: str
    map_link: Optional[str] = None
    zone: int = 0
    display_order: int
    is_active: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class HubRegistrarOfficeAdminResponse(BaseModel):
    """Admin response model with soft-delete fields."""
    id: UUID
    office_name: str
    phone_number: str
    city: str
    full_address: str
    map_link: Optional[str] = None
    zone: int = 0
    display_order: int
    is_active: bool
    created_at: str
    updated_at: str
    is_deleted: bool
    deleted_at: Optional[str] = None
    deleted_by: Optional[UUID] = None

    class Config:
        from_attributes = True
