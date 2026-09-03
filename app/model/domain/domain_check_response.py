"""Response contract for GET /api/v1/domain/check (homepage search + registration)."""

from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DomainCheckListingSnippet(BaseModel):
    """Matches frontend DomainSearchBar marketplace card (camelCase)."""

    id: UUID
    domainName: str
    domainExtension: str
    askingPrice: float
    domainStatus: Optional[str] = None
    saleType: Optional[str] = None


class DomainCheckResponse(BaseModel):
    status: Literal["marketplace", "available", "taken"]
    domain: str
    price: Optional[float] = None
    listing: Optional[DomainCheckListingSnippet] = None
    source: Optional[Literal["marketplace", "registrar", "openprovider"]] = None
    # Used by registration checkout; optional in API responses
    unitPrice: Optional[float] = Field(default=None, description="Per-year unit price at registrar")
    subtotalInr: Optional[float] = Field(
        default=None,
        description="Registration subtotal in INR (ex-GST base × years)",
    )
    gstInr: Optional[float] = Field(default=None, description="GST amount in INR")
    totalInr: Optional[float] = Field(
        default=None,
        description="Total payable in INR including GST",
    )
    gstRate: Optional[float] = Field(default=None, description="GST rate percent when enabled")
    gstEnabled: Optional[bool] = Field(default=None, description="Whether GST is applied at checkout")
    priceCurrency: Optional[str] = Field(
        default=None,
        description="Registrar reseller currency code (e.g. EUR, USD, INR)",
    )
    priceSource: Optional[str] = Field(
        default=None,
        description="Registrar price source",
    )
    minPeriodYears: Optional[int] = None
    demoMode: Optional[bool] = None
    registrarSandbox: Optional[bool] = Field(
        default=None,
        description="True when pricing/registration use test API",
    )
    registrarEnv: Optional[Literal["sandbox", "live"]] = None
    registrarApiBaseUrl: Optional[str] = None
    message: Optional[str] = None
    isPremium: Optional[bool] = Field(
        default=None,
        description="True when OpenProvider marks the domain as registry premium",
    )
    whoisPrivacyAllowed: Optional[bool] = Field(
        default=None,
        description="True when the TLD allows WHOIS privacy protection",
    )
    renewalPrice: Optional[float] = Field(
        default=None,
        description="Per-year renewal price in INR (if provided by registrar)",
    )
    renewalPriceInr: Optional[float] = Field(
        default=None,
        description="Per-year renewal price in INR including customer commission",
    )
