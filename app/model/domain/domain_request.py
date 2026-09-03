"""Pydantic request models for the domain module."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


def _normalize_extension(value: str | None) -> str | None:
    if value is None:
        return None
    ext = value.strip().lower()
    if not ext:
        return None
    if not ext.startswith("."):
        ext = f".{ext}"
    return ext


def _compose_domain_name(name: str, extension: str | None) -> str:
    normalized_name = name.strip().lower()
    if not normalized_name:
        raise ValueError("domain_name cannot be empty.")
    normalized_ext = _normalize_extension(extension)
    if normalized_ext and not normalized_name.endswith(normalized_ext):
        return f"{normalized_name}{normalized_ext}"
    return normalized_name


class CreateDomainRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="ignore",
        populate_by_name=True,
    )

    domain_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        validation_alias=AliasChoices("domain_name", "domainName"),
    )
    domain_extension: Optional[str] = Field(
        default=None,
        max_length=32,
        validation_alias=AliasChoices("domain_extension", "domainExtension"),
    )
    description: Optional[str] = Field(default=None, max_length=2000)
    pricing_demand: Optional[str] = Field(
        default=None,
        max_length=64,
        validation_alias=AliasChoices("pricing_demand", "pricingDemand"),
    )
    asking_price: Optional[float] = Field(
        default=None,
        validation_alias=AliasChoices("asking_price", "askingPrice"),
    )
    sale_type: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("sale_type", "saleType"),
    )
    contact_info: Optional[dict[str, Any]] = Field(
        default=None,
        validation_alias=AliasChoices("contact_info", "contactInfo"),
    )
    agreement: Optional[dict[str, Any]] = None

    @field_validator("domain_name")
    @classmethod
    def _normalize_name(cls, v: str) -> str:
        n = v.strip().lower()
        if not n:
            raise ValueError("domain_name cannot be empty.")
        return n

    @model_validator(mode="after")
    def _apply_compat_fields(self) -> "CreateDomainRequest":
        self.domain_name = _compose_domain_name(self.domain_name, self.domain_extension)
        if not self.description and self.pricing_demand:
            self.description = self.pricing_demand
        return self


class UpdateDomainRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="ignore",
        populate_by_name=True,
    )

    domain_name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        validation_alias=AliasChoices("domain_name", "domainName"),
    )
    domain_extension: Optional[str] = Field(
        default=None,
        max_length=32,
        validation_alias=AliasChoices("domain_extension", "domainExtension"),
    )
    description: Optional[str] = Field(default=None, max_length=2000)
    pricing_demand: Optional[str] = Field(
        default=None,
        max_length=64,
        validation_alias=AliasChoices("pricing_demand", "pricingDemand"),
    )
    asking_price: Optional[float] = Field(
        default=None,
        validation_alias=AliasChoices("asking_price", "askingPrice"),
    )
    sale_type: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("sale_type", "saleType"),
    )
    contact_info: Optional[dict[str, Any]] = Field(
        default=None,
        validation_alias=AliasChoices("contact_info", "contactInfo"),
    )
    agreement: Optional[dict[str, Any]] = None

    @field_validator("domain_name")
    @classmethod
    def _normalize_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        n = v.strip().lower()
        if not n:
            raise ValueError("domain_name cannot be empty.")
        return n

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "UpdateDomainRequest":
        if self.domain_name is not None:
            self.domain_name = _compose_domain_name(
                self.domain_name,
                self.domain_extension,
            )
        if not self.description and self.pricing_demand:
            self.description = self.pricing_demand
        if self.domain_name is None and self.description is None:
            raise ValueError("At least one field must be provided for update.")
        return self
