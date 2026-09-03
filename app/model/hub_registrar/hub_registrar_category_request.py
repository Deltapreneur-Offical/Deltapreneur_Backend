"""Hub Registrar Category request/response models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HubRegistrarCategoryCreateRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        populate_by_name=True,
        extra="forbid",
    )

    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=64)
    description: Optional[str] = Field(default=None, max_length=5000)
    starting_price: Optional[float] = Field(default=None, ge=0, validation_alias="startingPrice")
    icon: Optional[str] = Field(default=None, max_length=64)
    display_order: int = Field(default=0, ge=0, validation_alias="displayOrder")
    is_active: bool = Field(default=True, alias="isActive", validation_alias="isActive")

    @field_validator("name")
    @classmethod
    def _name_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

    @field_validator("slug")
    @classmethod
    def _slug_format(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must not be empty")
        normalized = value.strip().lower()
        # Only allow lowercase alphanumeric, underscores, and hyphens
        import re
        if not re.match(r"^[a-z0-9][a-z0-9_-]*$", normalized):
            raise ValueError(
                "slug must contain only lowercase letters, numbers, underscores, "
                "and hyphens, and must start with a letter or number"
            )
        return normalized


class HubRegistrarCategoryUpdateRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        populate_by_name=True,
        extra="forbid",
    )

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=5000)
    starting_price: Optional[float] = Field(default=None, ge=0, validation_alias="startingPrice")
    icon: Optional[str] = Field(default=None, max_length=64)
    display_order: Optional[int] = Field(default=None, ge=0, validation_alias="displayOrder")
    is_active: Optional[bool] = Field(default=None, alias="isActive", validation_alias="isActive")

    @field_validator("name")
    @classmethod
    def _name_non_empty(cls, value: str | None) -> str | None:
        if value is not None and (not value or not value.strip()):
            raise ValueError("must not be empty")
        return value.strip() if value else value
