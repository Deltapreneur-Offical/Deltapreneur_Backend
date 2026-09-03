"""Contracts for the AI Domains discovery engine."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AIDomainGenerateRequest(BaseModel):
    idea: str = Field(..., min_length=3, max_length=240)

    @field_validator("idea")
    @classmethod
    def clean_idea(cls, value: str) -> str:
        cleaned = " ".join(str(value or "").strip().split())
        if len(cleaned) < 3:
            raise ValueError("Enter a business idea with at least 3 characters.")
        return cleaned


class AIDomainCandidate(BaseModel):
    name: str = Field(..., min_length=3, max_length=24)
    score: int = Field(default=75, ge=0, le=100)
    category: str = Field(default="Startup")
    style: str = Field(default="Modern Startup", max_length=64)
    reason: str = Field(default="", max_length=240)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = "".join(ch for ch in str(value or "") if ch.isalnum())
        if len(cleaned) < 3:
            raise ValueError("Name is too short.")
        return cleaned[:24]

    @field_validator("style", "reason", "category")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return " ".join(str(value or "").strip().split())[:240]


class AIDomainAvailability(BaseModel):
    domain: str
    available: bool = False
    status: Literal["available", "taken", "checking", "unknown"] = "unknown"
    price_inr: float | None = None


class AIDomainResult(BaseModel):
    name: str
    domain_com: str
    com_available: bool = False
    com_status: Literal["available", "taken", "checking", "unknown"] = "unknown"
    domain_in: str
    in_available: bool = False
    in_status: Literal["available", "taken", "checking", "unknown"] = "unknown"
    com_price_inr: float | None = None
    in_price_inr: float | None = None
    score: int = Field(ge=0, le=100)
    brand_category: str
    style: str = "Modern Startup"
    reason: str = ""
    buy_action: str = "storefront"


class AIDomainGenerateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    idea: str
    category: str
    cached: bool = False
    results: list[AIDomainResult]
    generated_at: datetime
    rate_limit_remaining: int | None = None
    request_id: str | None = None
