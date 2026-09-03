"""Track Record entity for administrative transaction audit trails."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base.base import Base
from app.entity.base.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class TrackRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "track_records"
    __table_args__ = (
        Index("idx_track_records_created_at", "created_at"),
        Index("idx_track_records_category", "category"),
        Index("idx_track_records_overall_status", "overall_status"),
        Index("idx_track_records_buyer_email", "buyer_email"),
        Index("idx_track_records_razorpay_payment_id", "razorpay_payment_id"),
        Index("idx_track_records_razorpay_order_id", "razorpay_order_id"),
        Index("idx_track_records_internal_order_id", "internal_order_id"),
    )

    # Identifiers
    internal_order_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    cart_batch_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Categorization
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_subcategory: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    item_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    quantity_years: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Buyer Info
    buyer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    buyer_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    buyer_phone: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    buyer_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # Financial / Payment Details
    amount_charged: Mapped[float] = mapped_column(Numeric(12, 2), default=0.00, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    subtotal_ex_gst: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    gst_amount: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    payment_status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)
    razorpay_order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    razorpay_refund_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Fulfillment / Provisioning Info
    fulfillment_status: Mapped[str] = mapped_column(String(50), default="NOT_STARTED", nullable=False)
    overall_status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)
    openprovider_domain_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    provision_attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Diagnostics / Error Info
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Metadata & Notes
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    admin_deep_link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    def to_dict(self) -> dict:
        c_at = self.created_at.isoformat() if getattr(self, "created_at", None) else None
        u_at = self.updated_at.isoformat() if getattr(self, "updated_at", None) else None
        i_name = getattr(self, "item_name", None) or "Item"
        b_name = getattr(self, "buyer_name", None)
        b_email = getattr(self, "buyer_email", None)
        b_phone = getattr(self, "buyer_phone", None)
        amt = float(self.amount_charged) if getattr(self, "amount_charged", None) is not None else 0.0
        p_st = getattr(self, "payment_status", None) or "PENDING"
        f_st = getattr(self, "fulfillment_status", None) or "NOT_STARTED"
        o_st = getattr(self, "overall_status", None) or "PENDING"
        rzp_p = getattr(self, "razorpay_payment_id", None)
        rzp_o = getattr(self, "razorpay_order_id", None)
        cat = getattr(self, "category", None) or "Other"
        p_upper = str(p_st).upper()
        f_upper = str(f_st).upper()
        o_upper = str(o_st).upper()
        payment_ok = any(tok in p_upper for tok in ("CAPTURED", "PAID", "SUCCESS", "AUTHORIZED"))
        op_id = str(getattr(self, "openprovider_domain_id", None) or "").strip()
        cat_lower = str(cat).lower()
        is_domain_registration = "domain registration" in cat_lower
        is_domain_transfer = "domain transfer" in cat_lower
        # Category-aware operation type. Domain operations get their own
        # dedicated operation (Registration / Transfer / Renewal); non-domain
        # categories expose their real business operation instead — a
        # technology purchase must never be shown a Registration status.
        if is_domain_transfer:
            operation_type = "transfer"
            operation_title = "Transfer"
        elif "renewal" in cat_lower:
            operation_type = "renewal"
            operation_title = "Renewal"
        elif is_domain_registration:
            operation_type = "registration"
            operation_title = "Registration"
        elif "technology services" in cat_lower:
            operation_type = "provisioning"
            operation_title = "Provisioning"
        elif "technology purchase" in cat_lower:
            operation_type = "fulfillment"
            operation_title = "Fulfillment"
        elif "marketplace" in cat_lower or "managed acquisition" in cat_lower:
            operation_type = "acquisition"
            operation_title = "Acquisition"
        elif "venture" in cat_lower:
            operation_type = "deal"
            operation_title = "Deal"
        elif "addon" in cat_lower:
            operation_type = "service"
            operation_title = "Service"
        else:
            operation_type = None
            operation_title = None
        # Domain registrations are only Reg OK when a real OpenProvider id exists.
        # PROVISIONED/SUCCESS alone is not enough (old sync invented false Success rows).
        if is_domain_registration:
            registration_ok = (
                bool(op_id)
                and not op_id.upper().startswith("DEMO-")
                and "FAIL" not in f_upper
                and "FAIL" not in o_upper
            )
        elif is_domain_transfer:
            # Transfers are only OK once provisioned at the registrar. A transfer
            # in progress (Razorpay captured, OP pending) stays PENDING.
            registration_ok = (
                ("PROVISIONED" in f_upper or "ACTIVE" in f_upper)
                and bool(op_id)
                and not op_id.upper().startswith("DEMO-")
                and "FAIL" not in f_upper
                and "FAIL" not in o_upper
            )
        elif "renewal" in cat_lower:
            # A renewal completes when the registrar confirms it — reflected in
            # the fulfillment state, never inferred from registration success.
            registration_ok = (
                "PROVISIONED" in f_upper
                or "ACTIVE" in f_upper
                or "COMPLETED" in f_upper
                or "SUCCESS" in o_upper
            ) and "FAIL" not in f_upper and "FAIL" not in o_upper
        else:
            # Non-domain categories have NO registration operation — the admin
            # UI must render '—', never a guessed OK/FAIL/PENDING registration.
            registration_ok = False
        if operation_type in ("registration", "transfer", "renewal"):
            # The label follows the real fulfillment state: a genuine provider
            # failure is FAIL, a confirmed provisioning is OK, and an
            # in-progress registration (payment captured, provider processing)
            # is PENDING — never FAIL merely because the provider id is not
            # stamped yet.
            if "FAIL" in f_upper or "FAIL" in o_upper:
                registration_label = "FAIL"
            else:
                registration_label = "OK" if registration_ok else "PENDING"
        else:
            registration_label = "—"
        # Operation status for the dedicated Transfer/Renewal column: an
        # abandoned attempt (order expired/cancelled before payment) is
        # EXPIRED / CANCELLED — never PENDING (which would imply in-progress).
        if (
            (is_domain_transfer or "renewal" in cat_lower)
            and ("EXPIRED" in o_upper or "CANCELLED" in o_upper)
        ):
            operation_status = "EXPIRED" if "EXPIRED" in o_upper else "CANCELLED"
        elif operation_type in ("registration", "transfer", "renewal"):
            operation_status = registration_label
        elif operation_type in ("fulfillment", "provisioning", "acquisition", "deal", "service"):
            # Category-relevant business operation status — never derived from
            # a domain-registration lookup. Payment capture alone is not
            # completion, but a confirmed provisioning is OK.
            if "REFUND" in o_upper or "REFUND" in p_upper:
                operation_status = "REFUNDED"
            elif "EXPIRED" in o_upper:
                operation_status = "EXPIRED"
            elif "CANCELLED" in o_upper:
                operation_status = "CANCELLED"
            elif "FAIL" in f_upper or "FAIL" in o_upper:
                operation_status = "FAIL"
            elif (
                "PROVISIONED" in f_upper
                or "ACTIVE" in f_upper
                or "COMPLETED" in f_upper
                or "SUCCESS" in f_upper
                or "SUCCESS" in o_upper
            ):
                operation_status = "OK"
            else:
                operation_status = "PENDING"
        else:
            operation_status = None
        # Category-aware operation label: "Operation — status" (e.g.
        # "Fulfillment — Success", "Provisioning — Active",
        # "Registration — Pending"). The success word is category-specific:
        # provider-powered subscriptions are "Active", everything else is
        # "Success". The Operation column must never show a bare OK / FAIL /
        # PENDING.
        op_word = None
        if operation_status in ("OK", "PROVISIONED", "ACTIVE", "SUCCESS"):
            op_word = "Active" if operation_type == "provisioning" else "Success"
        elif operation_status in ("PENDING", "IN_PROGRESS", "NOT_STARTED"):
            op_word = "Pending"
        elif operation_status in ("FAIL", "FAILED"):
            op_word = "Failed"
        elif operation_status == "EXPIRED":
            op_word = "Expired"
        elif operation_status == "CANCELLED":
            op_word = "Cancelled"
        elif operation_status == "REFUNDED":
            op_word = "Refunded"
        operation_label = (
            f"{operation_title} — {op_word}"
            if operation_title and op_word
            else "—"
        )
        domain_name = None
        if i_name and not str(i_name).startswith("Payment #") and not str(i_name).startswith("Unprovisioned"):
            # Prefer FQDN-looking item names (single or comma-separated cart domains).
            candidate = str(i_name).split(",")[0].strip()
            if "." in candidate and " " not in candidate and "@" not in candidate:
                domain_name = str(i_name).strip()
        developer_summary = (
            "HubRegistrar Track Record Diagnostics\n"
            "---------------------------------\n"
            f"Time: {c_at or 'n/a'}\n"
            f"InternalOrderId: {getattr(self, 'internal_order_id', None) or 'n/a'}\n"
            f"CartBatchId: {getattr(self, 'cart_batch_id', None) or 'n/a'}\n"
            f"RazorpayOrderId: {rzp_o or 'n/a'}\n"
            f"RazorpayPaymentId: {rzp_p or 'n/a'}\n"
            f"Domain: {domain_name or '(not recovered)'}\n"
            f"Domain/Item: {i_name}\n"
            f"Category: {cat}\n"
            f"Buyer: {b_name or 'n/a'} / {b_email or 'n/a'} / "
            f"{getattr(self, 'buyer_user_id', None) or 'n/a'}\n"
            f"Phone: {b_phone or 'n/a'}\n"
            f"Amount: {amt} {getattr(self, 'currency', None) or 'INR'}\n"
            f"Payment: {'OK' if payment_ok else 'FAIL'} ({p_st})\n"
            f"{operation_title or 'Registration'}: {operation_status} (fulfillment={f_st}, overall={o_st})\n"
            f"OpenProviderDomainId: {getattr(self, 'openprovider_domain_id', None) or '(none)'}\n"
            f"ProvisionAttempts: {int(self.provision_attempts) if getattr(self, 'provision_attempts', None) is not None else 1}\n"
            f"ErrorSource: {getattr(self, 'error_source', None) or 'n/a'}\n"
            f"ErrorCode: {getattr(self, 'error_code', None) or 'n/a'}\n"
            f"ErrorMessage: {getattr(self, 'error_message', None) or 'n/a'}\n"
            f"Notes: {getattr(self, 'notes', None) or 'n/a'}\n"
        )

        return {
            "id": str(self.id) if getattr(self, "id", None) else None,
            "createdAt": c_at,
            "created_at": c_at,
            "updatedAt": u_at,
            "updated_at": u_at,
            "internalOrderId": getattr(self, "internal_order_id", None) or "N/A",
            "internal_order_id": getattr(self, "internal_order_id", None) or "N/A",
            "cartBatchId": getattr(self, "cart_batch_id", None),
            "category": cat,
            "providerSubcategory": getattr(self, "provider_subcategory", None),
            "provider_subcategory": getattr(self, "provider_subcategory", None),
            "itemName": i_name,
            "item_name": i_name,
            "domainName": domain_name,
            "domain_name": domain_name,
            "itemId": getattr(self, "item_id", None),
            "item_id": getattr(self, "item_id", None),
            "quantityYears": int(self.quantity_years) if getattr(self, "quantity_years", None) is not None else 1,
            "quantity_years": int(self.quantity_years) if getattr(self, "quantity_years", None) is not None else 1,
            "buyerName": b_name,
            "buyer_name": b_name,
            "buyerEmail": b_email,
            "buyer_email": b_email,
            "buyerPhone": b_phone,
            "buyer_phone": b_phone,
            "buyerUserId": str(self.buyer_user_id) if getattr(self, "buyer_user_id", None) else None,
            "buyer_user_id": str(self.buyer_user_id) if getattr(self, "buyer_user_id", None) else None,
            "amountCharged": amt,
            "amount_charged": amt,
            "currency": getattr(self, "currency", None) or "INR",
            "subtotalExGst": float(self.subtotal_ex_gst) if getattr(self, "subtotal_ex_gst", None) is not None else None,
            "gstAmount": float(self.gst_amount) if getattr(self, "gst_amount", None) is not None else None,
            "paymentStatus": p_st,
            "payment_status": p_st,
            "razorpayOrderId": rzp_o,
            "razorpay_order_id": rzp_o,
            "razorpayPaymentId": rzp_p,
            "razorpay_payment_id": rzp_p,
            "razorpayRefundId": getattr(self, "razorpay_refund_id", None),
            "fulfillmentStatus": f_st,
            "fulfillment_status": f_st,
            "overallStatus": o_st,
            "overall_status": o_st,
            "status": o_st,
            "openproviderDomainId": getattr(self, "openprovider_domain_id", None),
            "provisionAttempts": int(self.provision_attempts) if getattr(self, "provision_attempts", None) is not None else 1,
            "errorCode": getattr(self, "error_code", None),
            "errorMessage": getattr(self, "error_message", None),
            "errorSource": getattr(self, "error_source", None),
            "notes": getattr(self, "notes", None),
            "adminDeepLink": getattr(self, "admin_deep_link", None),
            # Additive diagnostics for Admin Track Records (no DB schema change).
            "paymentOk": payment_ok,
            "registrationOk": registration_ok,
            "registrationLabel": registration_label,
            "operationType": operation_type,
            "operation_type": operation_type,
            "operationTitle": operation_title,
            "operation_title": operation_title,
            "operationStatus": operation_status,
            "operation_status": operation_status,
            "operationLabel": operation_label,
            "operation_label": operation_label,
            "developerSummary": developer_summary,
            "developer_summary": developer_summary,
        }
