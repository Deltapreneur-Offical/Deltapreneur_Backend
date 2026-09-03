"""Post-sale domain marketplace transfer & escrow transaction."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.transfer_enums import (
    MarketplaceEscrowStatus,
    MarketplaceTransferStatus,
    TransferDisputeStatus,
    TransferMethod,
    TransferVerifiedBy,
)

if TYPE_CHECKING:
    from app.entity.cobranding.domain_listing_entity import DomainListing
    from app.entity.payout.seller_payout_profile_entity import SellerPayoutProfile
    from app.entity.user.app_user import AppUser


class DomainMarketplaceTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "domain_marketplace_transactions"
    __table_args__ = (
        Index("idx_dmt_seller_status", "seller_id", "transfer_status"),
        Index("idx_dmt_buyer_status", "buyer_id", "transfer_status"),
        Index("idx_dmt_seller_deadline", "transfer_status", "seller_deadline_at"),
        Index("idx_dmt_buyer_deadline", "transfer_status", "buyer_deadline_at"),
        Index("idx_dmt_escrow", "escrow_status"),
        Index("idx_dmt_listing", "domain_listing_id"),
    )

    domain_listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("domain_listings.id", ondelete="CASCADE"),
        nullable=False,
    )
    buyer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    domain_fqdn: Mapped[str] = mapped_column(String(320), nullable=False)

    gross_amount_inr: Mapped[float] = mapped_column(Float, nullable=False)
    platform_fee_inr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    seller_payout_inr: Mapped[float] = mapped_column(Float, nullable=False)

    razorpay_order_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, unique=True)
    razorpay_refund_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    escrow_status: Mapped[MarketplaceEscrowStatus] = mapped_column(
        SAEnum(MarketplaceEscrowStatus, name="marketplace_escrow_status_enum", create_constraint=False),
        default=MarketplaceEscrowStatus.HELD,
        nullable=False,
    )
    transfer_status: Mapped[MarketplaceTransferStatus] = mapped_column(
        SAEnum(MarketplaceTransferStatus, name="marketplace_transfer_status_enum", create_constraint=False),
        default=MarketplaceTransferStatus.AWAITING_AUTH_CODE,
        nullable=False,
    )
    transfer_method: Mapped[Optional[TransferMethod]] = mapped_column(
        SAEnum(TransferMethod, name="transfer_method_enum", create_constraint=False),
        nullable=True,
    )
    assistance_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    seller_registrar_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    buyer_target_registrar: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    auth_code_ciphertext: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auth_code_key_version: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    proof_storage_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    seller_deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    buyer_deadline_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    auth_code_submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    auth_code_viewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    transfer_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    transfer_confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    transfer_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    transfer_verified_by: Mapped[Optional[TransferVerifiedBy]] = mapped_column(
        SAEnum(TransferVerifiedBy, name="transfer_verified_by_enum", create_constraint=False),
        nullable=True,
    )
    whois_supports_transfer: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    payout_profile_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("seller_payout_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    payout_approved_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    payout_approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    payout_reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    payout_reminder_count: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    seller_paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    refund_completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    admin_review_required_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    admin_review_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    dispute_status: Mapped[TransferDisputeStatus] = mapped_column(
        SAEnum(TransferDisputeStatus, name="transfer_dispute_status_enum", create_constraint=False),
        default=TransferDisputeStatus.NONE,
        nullable=False,
    )
    cobrother_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )

    # --- Seller payout snapshot (historical, frozen at payout approval time) ---
    payout_snapshot_method: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    payout_snapshot_upi_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    payout_snapshot_account_holder: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    payout_snapshot_bank_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    payout_snapshot_account_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    payout_snapshot_ifsc: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    payout_snapshot_account_last4: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    payout_snapshot_captured_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    payout_snapshot_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    whois_last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    whois_registrar_snapshot: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    email_sale_seller_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_sale_buyer_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_seller_reminder_12h_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_seller_reminder_6h_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_auth_available_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_buyer_reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_admin_review_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_payout_released_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_refund_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    listing: Mapped["DomainListing"] = relationship(
        "DomainListing",
        foreign_keys=[domain_listing_id],
        lazy="selectin",
    )
    buyer: Mapped["AppUser"] = relationship("AppUser", foreign_keys=[buyer_id], lazy="selectin")
    seller: Mapped["AppUser"] = relationship("AppUser", foreign_keys=[seller_id], lazy="selectin")
    payout_profile: Mapped[Optional["SellerPayoutProfile"]] = relationship(
        "SellerPayoutProfile",
        foreign_keys=[payout_profile_id],
        lazy="selectin",
    )
