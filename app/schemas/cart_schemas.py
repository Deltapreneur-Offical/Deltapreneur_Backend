"""Pydantic request/response schemas for the shopping cart."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.utils.cart_enums import CartProductType


class AddToCartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    product_type: CartProductType = Field(..., alias="productType")
    product_id: uuid.UUID = Field(..., alias="productId")
    selected_plan: Optional[str] = Field(None, alias="selectedPlan")
    addon_services: Optional[list[str]] = Field(None, alias="addonServices")
    co_brother_opt_in: bool = Field(False, alias="coBrotherOptIn")
    metadata: Optional[dict[str, Any]] = Field(None, alias="metadata")


class UpdateCartItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    selected_plan: Optional[str] = Field(None, alias="selectedPlan")
    addon_services: Optional[list[str]] = Field(None, alias="addonServices")
    co_brother_opt_in: Optional[bool] = Field(None, alias="coBrotherOptIn")
    metadata: Optional[dict[str, Any]] = Field(None, alias="metadata")


class UpdateDomainRegistrationPeriodRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    period_years: int = Field(..., alias="periodYears", ge=1, le=10)
    # When set, only this DOMAIN_REGISTRATION cart line is re-quoted.
    # Required for multi-domain carts (each domain has its own period).
    item_id: Optional[uuid.UUID] = Field(None, alias="itemId")


class CartItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    product_type: CartProductType = Field(alias="productType")
    product_id: uuid.UUID = Field(alias="productId")
    selected_plan: Optional[str] = Field(None, alias="selectedPlan")
    addon_services: Optional[list[str]] = Field(None, alias="addonServices")
    co_brother_opt_in: bool = Field(alias="coBrotherOptIn")

    product_name: Optional[str] = Field(None, alias="productName")
    product_image: Optional[str] = Field(None, alias="productImage")
    base_price: float = Field(0.0, alias="basePrice")
    addon_amount: float = Field(0.0, alias="addonAmount")
    co_brother_fee: float = Field(0.0, alias="coBrotherFee")
    line_total: float = Field(0.0, alias="lineTotal")
    available: bool = True
    metadata: Optional[dict[str, Any]] = None


class CartResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[CartItemResponse]
    item_count: int = Field(alias="itemCount")
    subtotal: float = 0.0
    gst: float = 0.0
    total: float = 0.0
    currency: str = "INR"


class CartCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    redeem_points: bool = Field(False, alias="redeemPoints")
    currency: str = Field("INR")
    buyer_name: Optional[str] = Field(None, alias="buyerName")
    buyer_email: Optional[str] = Field(None, alias="buyerEmail")
    buyer_phone: Optional[str] = Field(None, alias="buyerPhone")
    # Additive: required only when cart contains DOMAIN_REGISTRATION items.
    registrant: Optional[dict[str, Any]] = Field(None, alias="registrant")
    # Deprecated: periods live on each cart item. Kept optional for old clients;
    # checkout always uses each item's metadata.period.
    period_years: Optional[int] = Field(None, alias="periodYears")


class CartCheckoutResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    order_id: str = Field(alias="orderId")
    amount: float
    currency: str = "INR"
    key_id: str = Field(alias="keyId")
    item_count: int = Field(alias="itemCount")
    buyer_name: Optional[str] = Field(None, alias="buyerName")
    buyer_email: Optional[str] = Field(None, alias="buyerEmail")
    buyer_phone: Optional[str] = Field(None, alias="buyerPhone")
    payment_description: Optional[str] = Field(None, alias="paymentDescription")
    payment_categories: Optional[str] = Field(None, alias="paymentCategories")


class CartVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    razorpay_order_id: str = Field(..., alias="razorpayOrderId")
    razorpay_payment_id: str = Field(..., alias="razorpayPaymentId")
    razorpay_signature: str = Field(..., alias="razorpaySignature")


class CartCancelCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    razorpay_order_id: str = Field(..., alias="razorpayOrderId")


class PremiumMarketplaceConfirmRequest(BaseModel):
    """No-payment confirmation for marketplace domains above ₹5L."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    full_name: Optional[str] = Field(None, alias="fullName")
    email: Optional[str] = None
    phone: Optional[str] = None
    message: Optional[str] = None
    listing_id: Optional[uuid.UUID] = Field(None, alias="listingId")


class OpenProviderManagedConfirmRequest(BaseModel):
    """No-payment confirmation for OpenProvider registrations above ₹5L payable."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    full_name: Optional[str] = Field(None, alias="fullName")
    email: Optional[str] = None
    phone: Optional[str] = None
    message: Optional[str] = None
    item_id: Optional[uuid.UUID] = Field(None, alias="itemId")
