"""Seller bank/UPI payout profile for marketplace transfers."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.transfer_enums import PayoutMethod, SellerKycStatus

if TYPE_CHECKING:
    from app.entity.user.app_user import AppUser


class SellerPayoutProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "seller_payout_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    payout_method: Mapped[PayoutMethod] = mapped_column(
        SAEnum(PayoutMethod, name="payout_method_enum", create_constraint=False),
        nullable=False,
    )
    account_holder_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bank_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    account_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    account_number_last4: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    bank_account_number_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bank_ifsc: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    upi_id_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kyc_status: Mapped[SellerKycStatus] = mapped_column(
        SAEnum(SellerKycStatus, name="seller_kyc_status_enum", create_constraint=False),
        default=SellerKycStatus.PENDING,
        nullable=False,
    )
    kyc_document_storage_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    beneficiary_validated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    beneficiary_validation_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped["AppUser"] = relationship(
        "AppUser",
        foreign_keys=[user_id],
        lazy="selectin",
    )
