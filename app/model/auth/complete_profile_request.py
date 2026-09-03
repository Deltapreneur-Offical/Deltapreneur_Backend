from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.field_validators import blank_to_none, normalize_profile_phone


class CompleteProfileRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        populate_by_name=True,
    )

    firstname: str = Field(..., min_length=1, max_length=100)
    lastname: str = Field(..., min_length=1, max_length=100)
    phone_number: str = Field(
        ...,
        min_length=10,
        max_length=15,
        alias="phoneNumber",
    )
    address: Optional[str] = Field(default=None, max_length=150)

    @field_validator("firstname", "lastname")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name fields cannot be empty")
        return v.strip()

    @field_validator("phone_number", mode="before")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return normalize_profile_phone(v)

    @field_validator("address", mode="before")
    @classmethod
    def _address(cls, v: str | None) -> str | None:
        return blank_to_none(v)
