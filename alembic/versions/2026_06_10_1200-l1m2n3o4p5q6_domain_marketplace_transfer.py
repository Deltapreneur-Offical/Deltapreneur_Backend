"""Domain marketplace transfer & escrow tables.

Revision ID: l1m2n3o4p5q6
Revises: k9l0m1n2o3p4
Create Date: 2026-06-10 12:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "l1m2n3o4p5q6"
down_revision: Union[str, Sequence[str], None] = "k9l0m1n2o3p4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    postgresql.ENUM("HELD", "RELEASED", "REFUNDED", name="marketplace_escrow_status_enum").create(
        bind, checkfirst=True,
    )
    postgresql.ENUM(
        "PAYMENT_COMPLETED", "AWAITING_AUTH_CODE", "AUTH_CODE_RECEIVED", "AUTH_CODE_VIEWED",
        "TRANSFER_IN_PROGRESS", "TRANSFER_COMPLETED", "PAYOUT_PENDING", "SELLER_PAID",
        "AUTH_CODE_TIMEOUT", "ADMIN_REVIEW_REQUIRED", "BUYER_TRANSFER_TIMEOUT",
        "REFUNDED", "DISPUTED", "CANCELLED",
        name="marketplace_transfer_status_enum",
    ).create(bind, checkfirst=True)
    postgresql.ENUM("SELF", "COBROTHER_ASSISTED", name="transfer_method_enum").create(
        bind, checkfirst=True,
    )
    postgresql.ENUM(
        "NONE", "OPEN", "UNDER_REVIEW", "RESOLVED_REFUND", "RESOLVED_PAYOUT", "CLOSED",
        name="transfer_dispute_status_enum",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "INVALID_AUTH_CODE", "SELLER_UNRESPONSIVE", "TRANSFER_ISSUE",
        name="dispute_reason_enum",
    ).create(bind, checkfirst=True)
    postgresql.ENUM("BUYER", "ADMIN", name="transfer_verified_by_enum").create(
        bind, checkfirst=True,
    )
    postgresql.ENUM(
        "PAYMENT_COMPLETED", "AUTH_SUBMITTED", "OTP_REVEAL", "TRANSFER_STARTED",
        "TRANSFER_CONFIRMED", "ASSISTANCE_REQUESTED", "ADMIN_REVIEW", "PAYOUT_PENDING",
        "PAYOUT_RELEASED", "REFUNDED", "DISPUTE_OPENED", "DISPUTE_RESOLVED", "WHOIS_CHECK",
        name="transfer_event_type_enum",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "PENDING", "SUBMITTED", "VERIFIED", "REJECTED", name="seller_kyc_status_enum",
    ).create(bind, checkfirst=True)
    postgresql.ENUM("BANK_ACCOUNT", "UPI", name="payout_method_enum").create(
        bind, checkfirst=True,
    )
    postgresql.ENUM(
        "PENDING", "APPROVED", "SENT", "FAILED", name="seller_payout_status_enum",
    ).create(bind, checkfirst=True)

    op.create_table(
        "seller_payout_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "payout_method",
            postgresql.ENUM(name="payout_method_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("account_holder_name", sa.String(255), nullable=False),
        sa.Column("bank_account_number_encrypted", sa.Text(), nullable=True),
        sa.Column("bank_ifsc", sa.String(16), nullable=True),
        sa.Column("upi_id_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "kyc_status",
            postgresql.ENUM(name="seller_kyc_status_enum", create_type=False),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("kyc_document_storage_key", sa.String(512), nullable=True),
        sa.Column("beneficiary_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("beneficiary_validation_ref", sa.String(128), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="true"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    op.create_table(
        "domain_marketplace_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("domain_listing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("buyer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain_fqdn", sa.String(320), nullable=False),
        sa.Column("gross_amount_inr", sa.Float(), nullable=False),
        sa.Column("platform_fee_inr", sa.Float(), nullable=False, server_default="0"),
        sa.Column("seller_payout_inr", sa.Float(), nullable=False),
        sa.Column("razorpay_order_id", sa.String(128), nullable=True),
        sa.Column("razorpay_payment_id", sa.String(128), nullable=True),
        sa.Column("razorpay_refund_id", sa.String(128), nullable=True),
        sa.Column(
            "escrow_status",
            postgresql.ENUM(name="marketplace_escrow_status_enum", create_type=False),
            nullable=False,
            server_default="HELD",
        ),
        sa.Column(
            "transfer_status",
            postgresql.ENUM(name="marketplace_transfer_status_enum", create_type=False),
            nullable=False,
            server_default="AWAITING_AUTH_CODE",
        ),
        sa.Column(
            "transfer_method",
            postgresql.ENUM(name="transfer_method_enum", create_type=False),
            nullable=True,
        ),
        sa.Column("assistance_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seller_registrar_name", sa.String(255), nullable=True),
        sa.Column("buyer_target_registrar", sa.String(255), nullable=True),
        sa.Column("auth_code_ciphertext", sa.Text(), nullable=True),
        sa.Column("auth_code_key_version", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("proof_storage_key", sa.String(512), nullable=True),
        sa.Column("seller_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("buyer_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auth_code_submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auth_code_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transfer_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transfer_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transfer_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "transfer_verified_by",
            postgresql.ENUM(name="transfer_verified_by_enum", create_type=False),
            nullable=True,
        ),
        sa.Column("whois_supports_transfer", sa.Boolean(), nullable=True),
        sa.Column("payout_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payout_approved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payout_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seller_paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refund_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_review_required_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_review_reason", sa.String(64), nullable=True),
        sa.Column(
            "dispute_status",
            postgresql.ENUM(name="transfer_dispute_status_enum", create_type=False),
            nullable=False,
            server_default="NONE",
        ),
        sa.Column("cobrother_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("whois_last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("whois_registrar_snapshot", sa.String(255), nullable=True),
        sa.Column("email_sale_seller_sent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("email_sale_buyer_sent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("email_seller_reminder_12h_sent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("email_seller_reminder_6h_sent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("email_auth_available_sent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("email_buyer_reminder_sent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("email_admin_review_sent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("email_payout_released_sent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("email_refund_sent", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["domain_listing_id"], ["domain_listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["buyer_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["seller_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["payout_profile_id"], ["seller_payout_profiles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["payout_approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("razorpay_payment_id"),
    )
    op.create_index("idx_dmt_seller_status", "domain_marketplace_transactions", ["seller_id", "transfer_status"])
    op.create_index("idx_dmt_buyer_status", "domain_marketplace_transactions", ["buyer_id", "transfer_status"])
    op.create_index(
        "idx_dmt_seller_deadline",
        "domain_marketplace_transactions",
        ["transfer_status", "seller_deadline_at"],
    )
    op.create_index(
        "idx_dmt_buyer_deadline",
        "domain_marketplace_transactions",
        ["transfer_status", "buyer_deadline_at"],
    )
    op.create_index("idx_dmt_escrow", "domain_marketplace_transactions", ["escrow_status"])
    op.create_index("idx_dmt_listing", "domain_marketplace_transactions", ["domain_listing_id"])

    op.add_column(
        "domain_listings",
        sa.Column("active_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_domain_listings_active_transaction_id",
        "domain_listings",
        "domain_marketplace_transactions",
        ["active_transaction_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "domain_transfer_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "event_type",
            postgresql.ENUM(name="transfer_event_type_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.String(16), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["transaction_id"], ["domain_marketplace_transactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_dte_transaction", "domain_transfer_events", ["transaction_id", "created_at"])

    op.create_table(
        "domain_disputes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("opened_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "reason",
            postgresql.ENUM(name="dispute_reason_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="OPEN"),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["transaction_id"], ["domain_marketplace_transactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["opened_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_domain_disputes_tx", "domain_disputes", ["transaction_id"])

    op.create_table(
        "domain_dispute_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispute_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=True),
        sa.ForeignKeyConstraint(["dispute_id"], ["domain_disputes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "seller_payouts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payout_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("amount_inr", sa.Float(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="seller_payout_status_enum", create_type=False),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("razorpay_payout_id", sa.String(128), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(512), nullable=True),
        sa.ForeignKeyConstraint(["transaction_id"], ["domain_marketplace_transactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["payout_profile_id"], ["seller_payout_profiles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("seller_payouts")
    op.drop_table("domain_dispute_evidence")
    op.drop_index("idx_domain_disputes_tx", table_name="domain_disputes")
    op.drop_table("domain_disputes")
    op.drop_index("idx_dte_transaction", table_name="domain_transfer_events")
    op.drop_table("domain_transfer_events")
    op.drop_constraint("fk_domain_listings_active_transaction_id", "domain_listings", type_="foreignkey")
    op.drop_column("domain_listings", "active_transaction_id")
    op.drop_index("idx_dmt_listing", table_name="domain_marketplace_transactions")
    op.drop_index("idx_dmt_escrow", table_name="domain_marketplace_transactions")
    op.drop_index("idx_dmt_buyer_deadline", table_name="domain_marketplace_transactions")
    op.drop_index("idx_dmt_seller_deadline", table_name="domain_marketplace_transactions")
    op.drop_index("idx_dmt_buyer_status", table_name="domain_marketplace_transactions")
    op.drop_index("idx_dmt_seller_status", table_name="domain_marketplace_transactions")
    op.drop_table("domain_marketplace_transactions")
    op.drop_table("seller_payout_profiles")

    bind = op.get_bind()
    for name in (
        "seller_payout_status_enum",
        "payout_method_enum",
        "seller_kyc_status_enum",
        "transfer_event_type_enum",
        "transfer_verified_by_enum",
        "dispute_reason_enum",
        "transfer_dispute_status_enum",
        "transfer_method_enum",
        "marketplace_transfer_status_enum",
        "marketplace_escrow_status_enum",
    ):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
