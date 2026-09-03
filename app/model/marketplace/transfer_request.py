"""Request DTOs for domain marketplace transfers."""

from __future__ import annotations

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.utils.transfer_enums import DisputeReason


class SubmitAuthCodeRequest(BaseModel):
    registrar_name: str = Field(..., alias="registrarName", min_length=1)
    auth_code: str = Field(..., alias="authCode", min_length=4)

    model_config = {"populate_by_name": True}


class ChooseSelfTransferRequest(BaseModel):
    buyer_target_registrar: str = Field(..., alias="buyerTargetRegistrar", min_length=1)

    model_config = {"populate_by_name": True}


class RevealOtpVerifyRequest(BaseModel):
    otp: str = Field(..., min_length=4, max_length=8)


class OpenDisputeRequest(BaseModel):
    reason: DisputeReason
    description: Optional[str] = None


class ResolveAdminReviewRequest(BaseModel):
    action: Literal["refund", "extend_deadline", "cancel"]
    extension_hours: Optional[int] = Field(None, alias="extensionHours", ge=1, le=168)

    model_config = {"populate_by_name": True}


class ResolveDisputeRequest(BaseModel):
    resolution: Literal["refund", "payout"]
    note: Optional[str] = None


class ForceCompleteRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=1024)


class SellerPayoutReminderRequest(BaseModel):
    transaction_id: uuid.UUID = Field(..., alias="transactionId")

    model_config = {"populate_by_name": True}


class ReleasePayoutRequest(BaseModel):
    payout_method_used: Literal["UPI", "BANK_TRANSFER"] = Field(..., alias="payoutMethodUsed")
    transaction_reference_number: str = Field(..., alias="transactionReferenceNumber", min_length=2)
    notes: Optional[str] = None

    model_config = {"populate_by_name": True}


class UpsertPayoutProfileRequest(BaseModel):
    payout_method: Literal["BANK_ACCOUNT", "UPI"] = Field(..., alias="payoutMethod")
    account_holder_name: str = Field(..., alias="accountHolderName", min_length=2)
    account_number: Optional[str] = Field(None, alias="accountNumber")
    bank_account_number: Optional[str] = Field(None, alias="bankAccountNumber")
    confirm_account_number: Optional[str] = Field(None, alias="confirmAccountNumber")
    bank_ifsc: Optional[str] = Field(None, alias="bankIfsc")
    upi_id: Optional[str] = Field(None, alias="upiId")

    model_config = {"populate_by_name": True}
