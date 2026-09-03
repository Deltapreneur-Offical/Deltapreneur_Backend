"""Pydantic schemas for domain-auction winner payment APIs (camelCase wire format)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.utils.enums import AuctionStatus, PaymentStatus


def payment_status_label(status: PaymentStatus) -> str:
    """Map DB PENDING to API CREATED for open Razorpay orders."""
    if status == PaymentStatus.PENDING:
        return "CREATED"
    return status.value


class PaymentAuctionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    domainId: uuid.UUID = Field(validation_alias="domain_id")
    status: AuctionStatus
    currentHighestBid: Optional[Decimal] = Field(
        default=None, validation_alias="current_highest_bid"
    )
    currentWinnerId: Optional[uuid.UUID] = Field(
        default=None, validation_alias="current_winner_id"
    )


class CreatePaymentOrderResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    orderId: str
    amount: Decimal
    currency: str = "INR"
    keyId: str
    auction: PaymentAuctionSummary
    paymentId: uuid.UUID
    status: str = "CREATED"


class VerifyPaymentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    success: bool
    message: str
    auctionId: uuid.UUID
    auctionStatus: AuctionStatus
    paymentStatus: str
    transferTransactionId: Optional[uuid.UUID] = None
    transferStatus: Optional[str] = None
