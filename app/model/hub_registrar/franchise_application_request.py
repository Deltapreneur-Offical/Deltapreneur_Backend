"""Franchise Application request/response models."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class FranchiseApplicationSubmitRequest(BaseModel):
    """Public submit request."""
    full_name: str = Field(..., min_length=1, max_length=255)
    mobile_number: str = Field(..., min_length=10, max_length=20)
    email: EmailStr = Field(...)
    city: str = Field(..., min_length=1, max_length=100)
    state: str = Field(..., min_length=1, max_length=100)
    full_address: str = Field(..., min_length=1)
    existing_business_name: Optional[str] = Field(None, max_length=255)
    business_type: Optional[str] = Field(None, max_length=100)
    preferred_location: Optional[str] = Field(None, max_length=255)
    existing_office_availability: Optional[str] = Field(None, max_length=100)
    relevant_experience: Optional[str] = None
    reason_for_applying: Optional[str] = None
    additional_information: Optional[str] = None
    map_url: Optional[str] = Field(None, max_length=500)


class FranchiseApplicationUpdateStatusRequest(BaseModel):
    """Admin status update request."""
    status: str = Field(..., pattern="^(REVIEWED|IN_PROGRESS|APPROVED|REJECTED)$")
    blacklist_reason: Optional[str] = None


class FranchiseApplicationBlacklistRequest(BaseModel):
    """Admin blacklist request."""
    reason: str = Field(..., min_length=1)
