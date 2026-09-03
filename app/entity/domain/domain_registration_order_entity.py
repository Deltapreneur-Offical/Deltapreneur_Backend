"""Domain registration storefront order."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.registration_enums import RegistrationOrderStatus

if TYPE_CHECKING:
    from app.entity.user.app_user import AppUser


class DomainRegistrationOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "domain_registration_orders"
    __table_args__ = (
        Index("idx_domain_reg_orders_buyer", "buyer_id"),
        Index("idx_domain_reg_orders_status", "status"),
        Index("idx_domain_reg_orders_rzp_order", "razorpay_order_id"),
        Index("idx_domain_reg_orders_rc_order", "resellerclub_order_id"),
    )

    domain_name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain_extension: Mapped[str] = mapped_column(String(32), nullable=False)

    buyer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    buyer_full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    buyer_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    buyer_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    street: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    zip_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    country: Mapped[str] = mapped_column(String(8), default="IN", nullable=False)
    # Optional buyer GSTIN captured at cart registrant checkout (for invoices).
    buyer_gstin: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)

    period_years: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    subtotal_inr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gst_inr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_inr: Mapped[float] = mapped_column(Float, nullable=False)

    razorpay_order_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    razorpay_refund_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    status: Mapped[RegistrationOrderStatus] = mapped_column(
        SAEnum(RegistrationOrderStatus, name="registration_order_status_enum", create_constraint=False),
        default=RegistrationOrderStatus.CREATED,
        nullable=False,
    )

    open_provider_handle: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    open_provider_domain_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    open_provider_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    resellerclub_customer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    resellerclub_contact_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    resellerclub_order_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    resellerclub_action_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    resellerclub_action_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    resellerclub_action_status_desc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resellerclub_invoice_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Aultum tax invoice id (AI + YY + 5 digits). Assigned only when status=ACTIVE.
    tax_invoice_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, unique=True)
    registrar_response_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quoted_unit_price_inr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Registry premium vs standard (OpenProvider is_premium). Distinct from
    # price_source which stores registrar quote tags (e.g. cart_checkout).
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    registry_tier: Mapped[str] = mapped_column(String(16), default="standard", nullable=False)
    provider_unit_price_inr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    provision_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provision_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    transfer_auth_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    transfer_status: Mapped[str] = mapped_column(String(64), default="NONE", nullable=False)
    renewal_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    pending_renewal_razorpay_order_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    pending_renewal_years: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pending_renewal_amount_inr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_renewal_payment_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Shared across N domain rows created from one cart checkout payment.
    batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    registrar_lock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    whois_privacy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    icann_verification_status: Mapped[str] = mapped_column(String(32), default="UNKNOWN", nullable=False)
    auto_renew_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    custom_nameservers: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dns_records_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_expiry_reminder_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    last_registrar_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    email_receipt_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_submitted_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_active_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_raa_pending_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_failed_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    buyer: Mapped["AppUser"] = relationship("AppUser", foreign_keys=[buyer_id], lazy="selectin")

    @property
    def fqdn(self) -> str:
        return f"{self.domain_name}{self.domain_extension}"
