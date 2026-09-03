"""Pydantic response models for the domain module."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List

from pydantic import BaseModel, ConfigDict, Field


class _ORMModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
    )


class DomainResponse(_ORMModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    domain_name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    is_verified: bool
    created_at: datetime
    updated_at: datetime


class DomainListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=200)
    items: List[DomainResponse]
