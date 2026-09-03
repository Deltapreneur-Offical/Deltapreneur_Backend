"""Webhooks, admin ops, and scheduled jobs for domain registration."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
from app.entity.user.app_user import AppUser
from app.integrations.razorpay import client as rzp
from app.repository.domain_registration_order_repository import (
    DomainRegistrationOrderRepository,
)
from app.service.domain.domain_registration_service import DomainRegistrationService
from app.utils.registration_enums import RegistrationOrderStatus

logger = logging.getLogger(__name__)


class DomainRegistrationOpsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._orders = DomainRegistrationOrderRepository(session)
        self._registration = DomainRegistrationService(session)

    async def handle_razorpay_webhook(
        self,
        body: bytes,
        signature: str,
    ) -> dict:
        logger.info(
            "razorpay.webhook.received bytes=%s signature_present=%s",
            len(body or b""),
            bool(signature),
        )
        if not rzp._webhook_secret():
            if settings.ENVIRONMENT == "production":
                raise AppException(
                    "Webhook secret is not configured.",
                    status_code=503,
                )
            logger.warning("razorpay.webhook.skipped reason=webhook_secret_not_configured")
            return {
                "ignored": True,
                "reason": "webhook secret not configured",
                "paymentAccepted": False,
                "registrationAttempted": False,
                "registrationSuccessful": False,
            }

        if not rzp.verify_webhook_signature(body, signature):
            logger.error("razorpay.webhook.signature_invalid")
            raise AppException("Invalid webhook signature.", status_code=400)

        logger.info("razorpay.webhook.signature_verified")

        payload = json.loads(body)
        event = payload.get("event", "")
        inner = payload.get("payload") or {}
        payment_wrap = inner.get("payment") or {}
        entity = payment_wrap.get("entity") if isinstance(payment_wrap, dict) else {}
        if not entity:
            entity = payment_wrap if isinstance(payment_wrap, dict) else {}

        order_id = entity.get("order_id")
        payment_id = entity.get("id")
        logger.info(
            "razorpay.webhook.parsed event=%s order_id=%s payment_id=%s",
            event,
            order_id,
            payment_id,
        )

        if event == "payment.captured" and order_id:
            outcome = await self._registration.complete_payment_from_webhook(
                order_id, payment_id,
            )
            orders_found = int(outcome.get("ordersFound") or 0)
            registration_attempted = bool(outcome.get("registrationAttempted"))
            registration_successful = bool(outcome.get("registrationSuccessful"))
            needs_attention = bool(outcome.get("needsAttention")) or orders_found == 0

            if orders_found == 0:
                logger.warning(
                    "razorpay.webhook.orders_found=0 order_id=%s payment_id=%s "
                    "REGISTRATION_NOT_ATTEMPTED — no domain_registration_orders row for this "
                    "Razorpay order. Payment was accepted by Razorpay but OpenProvider "
                    "register_domain was NEVER called.",
                    order_id,
                    payment_id,
                )
            else:
                logger.info(
                    "razorpay.webhook.orders_found=%s order_id=%s payment_id=%s "
                    "registrationAttempted=%s registrationSuccessful=%s needsAttention=%s",
                    orders_found,
                    order_id,
                    payment_id,
                    registration_attempted,
                    registration_successful,
                    needs_attention,
                )

            return {
                # HTTP layer accepted the webhook (Razorpay should not retry endlessly).
                "processed": True,
                "event": event,
                # Explicit payment vs registration separation for ops/dev.
                "paymentAccepted": True,
                "registrationAttempted": registration_attempted,
                "registrationSuccessful": registration_successful,
                "ordersFound": orders_found,
                "needsAttention": needs_attention,
                "skipReason": outcome.get("skipReason"),
                "results": outcome.get("results") or [],
            }

        if event == "payment.failed" and order_id:
            orders = await self._orders.list_by_razorpay_order_id(order_id)
            updated_count = 0
            for order in orders:
                # Only mark CREATED orders as failed. Never downgrade
                # PAYMENT_COMPLETED or later states — a stale payment.failed
                # from an earlier attempt must not override a valid capture.
                if order.status == RegistrationOrderStatus.CREATED:
                    order.status = RegistrationOrderStatus.PAYMENT_FAILED
                    await self._orders.save(order)
                    updated_count += 1
                else:
                    logger.info(
                        "razorpay.webhook.payment_failed.skipped order_id=%s "
                        "payment_id=%s domain=%s%s current_status=%s — "
                        "not downgrading post-payment status",
                        order_id,
                        payment_id,
                        order.domain_name,
                        order.domain_extension,
                        order.status,
                    )
            if updated_count:
                await self._session.commit()
            logger.info(
                "razorpay.webhook.payment_failed order_id=%s payment_id=%s "
                "ordersFound=%s ordersUpdated=%s",
                order_id,
                payment_id,
                len(orders),
                updated_count,
            )
            return {
                "processed": True,
                "event": event,
                "paymentAccepted": False,
                "registrationAttempted": False,
                "registrationSuccessful": False,
                "ordersUpdated": updated_count,
            }

        if event == "refund.processed":
            orders = (
                list(await self._orders.list_by_razorpay_order_id(order_id))
                if order_id
                else []
            )
            for order in orders:
                order.status = RegistrationOrderStatus.REFUNDED
                order.razorpay_refund_id = entity.get("id")
                await self._orders.save(order)
            if orders:
                await self._session.commit()
            logger.info(
                "razorpay.webhook.refund_processed order_id=%s ordersUpdated=%s",
                order_id,
                len(orders),
            )
            return {
                "processed": True,
                "event": event,
                "paymentAccepted": True,
                "registrationAttempted": False,
                "registrationSuccessful": False,
                "ordersUpdated": len(orders),
            }

        logger.info("razorpay.webhook.ignored_event event=%s", event)
        return {
            "processed": False,
            "event": event,
            "paymentAccepted": False,
            "registrationAttempted": False,
            "registrationSuccessful": False,
        }

    async def handle_openprovider_callback(self, body: dict) -> dict:
        domain_id = body.get("domain_id") or body.get("id")
        status_raw = str(body.get("status", "")).upper()
        logger.info("OpenProvider callback domain_id=%s status=%s", domain_id, status_raw)

        if not domain_id:
            raise AppException("Missing domain identifier in callback.", status_code=400)

        order = await self._orders.get_by_openprovider_domain_id(str(domain_id))
        if order is None:
            logger.warning("OpenProvider callback for unknown domain_id=%s", domain_id)
            return {"received": True, "matched": False}

        order.open_provider_status = status_raw or order.open_provider_status
        active_statuses = {"ACT", "ACTIVE", "OK", "COMPLETED"}
        failed_statuses = {"FAILED", "REJECTED", "EXPIRED", "CANCELLED"}

        if status_raw in active_statuses:
            if order.status != RegistrationOrderStatus.ACTIVE:
                order.status = RegistrationOrderStatus.ACTIVE
                order.completed_at = datetime.now(timezone.utc)
                order.provision_message = "Domain activated via registrar callback."
        elif status_raw in failed_statuses:
            order.status = RegistrationOrderStatus.PROVISION_FAILED
            order.provision_message = body.get("message") or "Registrar reported failure."

        await self._orders.save(order)
        await self._session.commit()
        return {
            "received": True,
            "matched": True,
            "orderId": str(order.id),
            "status": order.status.value,
        }

    async def admin_list_orders(
        self,
        *,
        status: str | None = None,
    ) -> list[dict]:
        parsed = RegistrationOrderStatus(status) if status else None
        orders = await self._orders.list_all(status=parsed)
        from app.utils.registration_lifecycle import registration_lifecycle_status

        result = []
        for o in orders:
            buyer_name = o.buyer_full_name
            if not buyer_name and getattr(o, "buyer", None):
                buyer_name = f"{o.buyer.firstname or ''} {o.buyer.lastname or ''}".strip()
            buyer_email = o.buyer_email
            if not buyer_email and getattr(o, "buyer", None):
                buyer_email = o.buyer.email
            buyer_phone = o.buyer_phone
            if not buyer_phone and getattr(o, "buyer", None):
                buyer_phone = o.buyer.phone_number

            result.append({
                "id": str(o.id),
                "domain": o.fqdn,
                "status": o.status.value if hasattr(o.status, "value") else str(o.status),
                "lifecycleStatus": registration_lifecycle_status(o),
                "priceInr": o.price_inr,
                "buyerId": str(o.buyer_id),
                "buyerName": buyer_name,
                "buyerEmail": buyer_email,
                "buyerPhone": buyer_phone,
                "razorpayOrderId": o.razorpay_order_id,
                "razorpayPaymentId": o.razorpay_payment_id,
                "registrar": "OpenProvider",
                "openProviderDomainId": o.open_provider_domain_id,
                "openProviderHandle": o.open_provider_handle,
                "openProviderStatus": o.open_provider_status,
                "provisionMessage": o.provision_message,
                "provisionAttempts": o.provision_attempts,
                "icannVerificationStatus": o.icann_verification_status,
                "createdAt": o.created_at.isoformat() if o.created_at else None,
                "updatedAt": o.updated_at.isoformat() if o.updated_at else None,
                "completedAt": o.completed_at.isoformat() if o.completed_at else None,
                "expiresAt": o.expires_at.isoformat() if o.expires_at else None,
                "periodYears": o.period_years,
                "isPremium": bool(getattr(o, "is_premium", False)),
                "canRetry": o.status in (
                    RegistrationOrderStatus.PROVISION_FAILED,
                    RegistrationOrderStatus.PAYMENT_COMPLETED,
                    RegistrationOrderStatus.REGISTRATION_PENDING,
                ),
                "canRefund": o.status == RegistrationOrderStatus.ACTIVE and bool(o.razorpay_payment_id),
            })
        return result

    async def admin_retry(self, order_id: uuid.UUID) -> dict:
        order = await self._orders.get_by_id(order_id)
        if order is None:
            raise AppException("Order not found.", status_code=404)
        await self._registration.provision_order(order)
        await self._session.commit()
        order = await self._orders.get_by_id(order_id)
        return self._registration._provision_response(order)

    async def admin_refund(self, order_id: uuid.UUID) -> dict:
        order = await self._orders.get_by_id(order_id)
        if order is None:
            raise AppException("Order not found.", status_code=404)
        if not order.razorpay_payment_id:
            raise AppException("No payment to refund.", status_code=400)
        refund = rzp.refund_payment(order.razorpay_payment_id, order.price_inr)
        order.status = RegistrationOrderStatus.REFUNDED
        order.razorpay_refund_id = refund.get("id")
        await self._orders.save(order)
        await self._session.commit()
        return {"success": True, "refundId": order.razorpay_refund_id}

    async def admin_set_tax_invoice(self, order_id: uuid.UUID, tax_invoice_number: str) -> dict:
        """Set/replace tax invoice number for an ACTIVE registration (admin privilege)."""
        from app.service.domain.tax_invoice_number_service import admin_set_tax_invoice_number

        payload = await admin_set_tax_invoice_number(
            self._session,
            order_id,
            tax_invoice_number,
        )
        await self._session.commit()
        return {"success": True, **payload}

    async def run_provision_retries(
        self,
        *,
        max_attempts: int | None = None,
    ) -> int:
        attempts = max_attempts or settings.DOMAIN_REGISTRATION_MAX_PROVISION_ATTEMPTS
        try:
            orders = await self._orders.list_provision_retry_candidates(
                max_attempts=attempts,
            )
        except ProgrammingError as exc:
            await self._session.rollback()
            logger.warning(
                "domain provision retries skipped (run alembic upgrade head): %s",
                exc.orig if hasattr(exc, "orig") else exc,
            )
            return 0
        count = 0
        for order in orders:
            # Domain transfers are handled exclusively by the transfer flow
            # (_provision_transfer). They must never reach provision_order(),
            # which hard-refuses transfers and would abort this scheduler tick.
            if order.transfer_status and order.transfer_status != "NONE":
                continue

            if (
                order.open_provider_domain_id
                and order.status == RegistrationOrderStatus.REGISTRATION_PENDING
            ):
                from app.service.domain.domain_registration_followup import (
                    DomainRegistrationFollowup,
                )

                followup = DomainRegistrationFollowup(self._session)
                confirmed, order = await followup.sync_from_registrar(order)
                if confirmed:
                    await followup.send_lifecycle_emails(order)
                count += 1
                continue
            await self._registration.provision_order(order)
            count += 1
        if count:
            await self._session.commit()
        return count

    async def run_pending_reconcile(self) -> int:
        from app.service.domain.domain_registration_followup import (
            DomainRegistrationFollowup,
        )

        followup = DomainRegistrationFollowup(self._session)
        return await followup.run_pending_reconcile_batch()

    async def run_transfer_reconcile(self) -> int:
        """Retry paid transfers that were never submitted (provider unavailable)."""
        from app.service.domain.domain_registration_followup import (
            DomainRegistrationFollowup,
        )

        followup = DomainRegistrationFollowup(self._session)
        return await followup.run_transfer_pending_reconcile()

    async def run_stale_pending_alerts(self) -> int:
        from app.service.domain.domain_registration_followup import (
            DomainRegistrationFollowup,
        )

        followup = DomainRegistrationFollowup(self._session)
        return await followup.run_stale_pending_alerts()

    async def recover_stale_registration_pending(self) -> dict:
        from app.service.domain.domain_registration_followup import (
            DomainRegistrationFollowup,
        )

        followup = DomainRegistrationFollowup(self._session)
        return await followup.recover_stale_registration_pending()

    async def expire_stale_orders(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        orders = await self._orders.list_stale_unpaid(cutoff)
        for order in orders:
            order.status = RegistrationOrderStatus.EXPIRED
            await self._orders.save(order)
        if orders:
            await self._session.commit()
        return len(orders)
