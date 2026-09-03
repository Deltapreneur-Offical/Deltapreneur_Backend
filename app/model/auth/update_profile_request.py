"""Partial profile update (Java PUT /api/v1/auth/profile/update)."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.field_validators import blank_to_none, normalize_profile_phone


class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="ignore",
        populate_by_name=True,
    )

    firstname: Optional[str] = Field(None, max_length=100)
    lastname: Optional[str] = Field(None, max_length=100)
    phone_number: Optional[str] = Field(None, max_length=20, alias="phoneNumber")
    address: Optional[str] = Field(None, max_length=150)
    username: Optional[str] = Field(None, max_length=100)

    @field_validator("firstname", "lastname", mode="before")
    @classmethod
    def _optional_name(cls, v: str | None) -> str | None:
        raw = blank_to_none(v)
        if raw is None:
            return None
        if not raw.strip():
            raise ValueError("Name fields cannot be empty")
        return raw.strip()

    @field_validator("phone_number", mode="before")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return normalize_profile_phone(v)

    @field_validator("address", "username", mode="before")
    @classmethod
    def _blank_optional(cls, v: str | None) -> str | None:
        return blank_to_none(v)
