"""Operations service API response models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class OperationsServiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    name: str
    category: str
    description: Optional[str] = None
    price: float
    is_available: bool = Field(serialization_alias="isAvailable")
    icon: Optional[str] = None
    display_order: int = Field(serialization_alias="displayOrder")
    skills: Optional[str] = None
    service_type: str = Field(default="virtual_assistance", serialization_alias="serviceType")
    government_fees_applicable: bool = Field(default=False, serialization_alias="governmentFeesApplicable")
    government_fee_text: str = Field(default="Government fees applicable", serialization_alias="governmentFeeText")
    views: int = 0
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")
    updated_at: Optional[datetime] = Field(default=None, serialization_alias="updatedAt")
