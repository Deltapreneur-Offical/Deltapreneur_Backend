"""Technology Services provisioning retry / reconciliation worker.

Guarantees of this worker:

* It ONLY processes paid subscriptions (``payment_status = CAPTURED``) in
  ``PENDING`` / ``PROVISIONING_FAILED`` whose ``next_retry_at`` is due and
  whose attempt count is below the configured maximum.
* It NEVER calls Razorpay — payment is a read-only input.
* Because ResellPortal ``POST /orders`` has NO idempotency, every retry
  first reconciles existing provider orders via ``GET /orders`` and adopts a
  matching order instead of submitting a duplicate.
* It uses row locking (``FOR UPDATE SKIP LOCKED``) so concurrent ticks /
  replicas cannot provision the same subscription twice.
* It records attempt counts, provider status/error and next-retry backoff on
  the subscription, and stops automatically after the retry limit, marking
  the subscription ``needs_review`` for admin intervention.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.entity.technology_services.technology_service_entity import TechnologyServiceEntity
from app.entity.technology_services.technology_subscription_entity import TechnologySubscriptionEntity
from app.entity.user.app_user import AppUser
from app.integrations.resellportal.client import get_resellportal_client
from app.service.auth.mail_service import MailService
from app.service.platform.track_record_service import (
    FulfillmentStatus,
    OverallStatus,
    PaymentStatus,
    TrackRecordCategory,
    TrackRecordService,
)
from app.service.resellportal.product_mapper import (
    build_order_parameters,
    get_product_key,
    is_provider_mapped,
    validate_order_input,
)

logger = logging.getLogger(__name__)

# Exponential backoff between automatic provisioning attempts (minutes).
BACKOFF_MINUTES = (5, 15, 60, 360, 1440)  # 5m, 15m, 1h, 6h, 24h

# Subscription statuses the worker may retry.
RETRYABLE_STATUSES = ("PENDING", "PROVISIONING_FAILED")


def _backoff_delay(attempt_number: int) -> timedelta:
    """Backoff after ``attempt_number`` attempts (1-based)."""
    idx = min(max(attempt_number - 1, 0), len(BACKOFF_MINUTES) - 1)
    return timedelta(minutes=BACKOFF_MINUTES[idx])


def _sub_periods(billing_cycle: str) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    days = 365 if str(billing_cycle or "").lower().startswith("ann") else 30
    return now, now + timedelta(days=days)


class TechnologySubscriptionRetryService:
    """Retry / reconcile paid Technology Service subscriptions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._track_service = TrackRecordService(session)
        self._client = get_resellportal_client()
        self._max_retries = max(1, int(settings.TECH_SUBSCRIPTION_MAX_RETRIES))

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def run_tick(self) -> dict[str, int]:
        """Scan and process due subscriptions. Returns stats for logging."""
        stats = {"processed": 0, "adopted": 0, "activated": 0, "pending": 0, "failed": 0, "needs_input": 0}
        now = datetime.now(timezone.utc)
        stmt = (
            select(TechnologySubscriptionEntity)
            .where(
                TechnologySubscriptionEntity.status.in_(RETRYABLE_STATUSES),
                TechnologySubscriptionEntity.payment_status == PaymentStatus.CAPTURED,
                TechnologySubscriptionEntity.is_deleted.is_(False),
                TechnologySubscriptionEntity.provision_attempts < self._max_retries,
                (
                    TechnologySubscriptionEntity.next_retry_at.is_(None)
                    | (TechnologySubscriptionEntity.next_retry_at <= now)
                ),
            )
            .order_by(TechnologySubscriptionEntity.created_at.asc())
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        for sub in rows:
            outcome = await self._process(sub)
            stats[outcome] = stats.get(outcome, 0) + 1
            stats["processed"] += 1
        if stats["processed"]:
            await self._session.commit()
            logger.info("technology.retry.tick processed=%s stats=%s", stats["processed"], stats)
        return stats

    async def retry_subscription(
        self,
        subscription_id: str | uuid.UUID,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        """Retry a single subscription now (admin action or inline customer input).

        ``force`` bypasses the retry-limit guard so an admin can re-attempt a
        subscription that exhausted automatic retries.
        """
        stmt = (
            select(TechnologySubscriptionEntity)
            .where(TechnologySubscriptionEntity.id == subscription_id)
            .with_for_update()
        )
        result = await self._session.execute(stmt)
        sub = result.scalar_one_or_none()
        if sub is None:
            return {"success": False, "error": "Subscription not found"}

        if sub.status == "ACTIVE":
            return {"success": False, "error": "Subscription is already active"}

        if sub.payment_status != PaymentStatus.CAPTURED:
            return {"success": False, "error": "Subscription is not paid; refusing to provision"}

        if not force and sub.provision_attempts >= self._max_retries:
            return {"success": False, "error": "Automatic retry limit reached; needs review"}

        # Reset the schedule for a manual retry.
        sub.next_retry_at = datetime.now(timezone.utc)
        sub.needs_review = False
        outcome = await self._process(sub)
        await self._session.commit()
        return {"success": outcome in ("activated", "pending", "adopted"), "outcome": outcome, "status": sub.status}

    # ------------------------------------------------------------------ #
    # Core processing
    # ------------------------------------------------------------------ #

    async def _process(self, sub: TechnologySubscriptionEntity) -> str:
        """Process one subscription. Returns a stats outcome label."""
        try:
            # 1. Resolve the service and confirm provider mapping.
            service = await self._service_for(sub.service_slug)
            product_key = None
            if service is not None:
                product_key = getattr(service, "provider_product_key", None) or get_product_key(service.slug)
            else:
                product_key = get_product_key(sub.service_slug)

            if not product_key or not is_provider_mapped(sub.service_slug):
                # Not provider-mapped (e.g. WordPress Plugin Pack) → manual
                # fulfillment only. Never POST /orders.
                return await self._mark_manual_fulfillment(sub)

            user = await self._user_for(sub.user_id)
            user_email = user.email if user is not None else sub.user_id

            # 2. NEVER blindly POST /orders: reconcile existing provider orders first.
            existing = self._client.find_matching_order(
                service_slug=sub.service_slug,
                user_id=sub.user_id,
                product_key=product_key,
                user_email=user_email,
                plan_code=sub.plan_code,
                billing_cycle=sub.billing_cycle,
            )
            if existing is not None:
                return await self._adopt_existing_order(sub, existing, user_email)

            # 3. Validate required customer input before provisioning.
            metadata = self._subscription_metadata(sub)
            ok, missing = validate_order_input(sub.service_slug, metadata)
            if not ok:
                sub.status = "PENDING"
                sub.needs_review = True
                sub.last_provider_error = (
                    f"{sub.service_name} requires: {', '.join(missing)}. "
                    "Please provide the required information to activate."
                )
                await self._session.flush()
                await self._update_track(sub, FulfillmentStatus.IN_PROGRESS, OverallStatus.PENDING, error_message=sub.last_provider_error)
                await self._send_pending_email(sub, user_email, needs_input=True)
                return "needs_input"

            # 4. Provision (reconciliation already confirmed no existing order).
            order_parameters = build_order_parameters(
                product_key=product_key,
                plan_code=sub.plan_code,
                billing_cycle=sub.billing_cycle,
                metadata=metadata,
            )
            sub.status = "PROVISIONING"
            sub.last_provision_attempt_at = datetime.now(timezone.utc)
            sub.provision_attempts += 1
            sub.last_provider_status = None
            sub.last_provider_error = None
            await self._session.flush()

            prov_res = self._client.provision_service(
                service_slug=sub.service_slug,
                service_name=sub.service_name,
                plan_code=sub.plan_code,
                billing_cycle=sub.billing_cycle,
                user_email=user_email,
                user_id=sub.user_id,
                product_key=product_key,
                order_parameters=order_parameters,
            )

            provider_success = prov_res.get("success") is True
            provider_status = str(prov_res.get("status") or "PENDING").upper()
            sub.last_provider_status = provider_status
            sub.last_provider_error = str(prov_res.get("error") or "") if not provider_success else None

            if provider_success and provider_status == "ACTIVE":
                return await self._mark_active(sub, prov_res, user_email)
            if provider_success and provider_status in ("PENDING", "PROVISIONING_PENDING"):
                return await self._mark_pending(sub, prov_res, user_email)
            return await self._mark_failed(sub, prov_res, user_email)
        except Exception:
            logger.exception("technology.retry.process_failed sub=%s", sub.id)
            sub.status = "PROVISIONING_FAILED"
            sub.last_provider_error = "Unexpected error during provisioning retry."
            sub.needs_review = True
            await self._session.flush()
            return "failed"

    # ------------------------------------------------------------------ #
    # Outcome handlers
    # ------------------------------------------------------------------ #

    async def _mark_active(self, sub, prov_res, user_email: str) -> str:
        sub.status = "ACTIVE"
        sub.provider_order_id = prov_res.get("provider_order_id") or sub.provider_order_id
        sub.provider_subscription_id = prov_res.get("provider_subscription_id") or sub.provider_subscription_id
        sub.credentials_json = json.dumps(prov_res.get("credentials") or {})
        start, end = prov_res.get("current_period_start"), prov_res.get("current_period_end")
        if start is None or end is None:
            start, end = _sub_periods(sub.billing_cycle)
        sub.current_period_start = start
        sub.current_period_end = end
        sub.next_retry_at = None
        sub.needs_review = False
        sub.last_provider_error = None
        await self._session.flush()
        await self._update_track(sub, FulfillmentStatus.PROVISIONED, OverallStatus.SUCCESS)
        await self._send_confirmation_email(sub, user_email)
        return "activated"

    async def _mark_pending(self, sub, prov_res, user_email: str) -> str:
        sub.status = "PENDING"
        sub.provider_order_id = prov_res.get("provider_order_id") or sub.provider_order_id
        sub.provider_subscription_id = prov_res.get("provider_subscription_id") or sub.provider_subscription_id
        if prov_res.get("credentials"):
            sub.credentials_json = json.dumps(prov_res.get("credentials"))
        sub.next_retry_at = self._next_retry(sub)
        await self._session.flush()
        await self._update_track(sub, FulfillmentStatus.IN_PROGRESS, OverallStatus.PENDING)
        await self._send_pending_email(sub, user_email, needs_input=False)
        return "pending"

    async def _mark_failed(self, sub, prov_res, user_email: str) -> str:
        sub.status = "PROVISIONING_FAILED"
        sub.last_provider_error = str(
            prov_res.get("error") or prov_res.get("message") or "Provider provisioning failed."
        )
        sub.next_retry_at = self._next_retry(sub)
        await self._session.flush()
        await self._update_track(
            sub,
            FulfillmentStatus.FAILED,
            OverallStatus.FAILED,
            error_code="PROVISIONING_ERROR",
            error_message=sub.last_provider_error,
        )
        await self._send_failed_email(sub, user_email)
        return "failed"

    async def _adopt_existing_order(self, sub, existing: dict[str, Any], user_email: str) -> str:
        """Adopt an existing provider order — never create a duplicate."""
        sub.provider_order_id = existing.get("provider_order_id") or existing.get("order_id") or sub.provider_order_id
        sub.provider_subscription_id = (
            existing.get("provider_subscription_id") or existing.get("subscription_id") or sub.provider_subscription_id
        )
        provider_status = str(existing.get("status") or "PENDING").upper()
        sub.last_provider_status = provider_status
        if provider_status == "ACTIVE":
            sub.status = "ACTIVE"
            sub.next_retry_at = None
            sub.needs_review = False
            sub.last_provider_error = None
            if sub.current_period_start is None or sub.current_period_end is None:
                sub.current_period_start, sub.current_period_end = _sub_periods(sub.billing_cycle)
            await self._session.flush()
            await self._update_track(sub, FulfillmentStatus.PROVISIONED, OverallStatus.SUCCESS)
            await self._send_confirmation_email(sub, user_email)
            return "adopted"
        # Provider order exists but is not active yet.
        sub.status = "PENDING"
        sub.next_retry_at = self._next_retry(sub)
        await self._session.flush()
        await self._update_track(sub, FulfillmentStatus.IN_PROGRESS, OverallStatus.PENDING)
        return "pending"

    async def _mark_manual_fulfillment(self, sub) -> str:
        sub.status = "PENDING"
        sub.needs_review = True
        sub.last_provider_status = "MANUAL_FULFILLMENT_REQUIRED"
        sub.last_provider_error = "This service has no automated provider mapping. Manual fulfillment required."
        sub.next_retry_at = None  # never auto-retry a manual service
        # Exclude from the automatic worker scan: admin fulfills manually.
        sub.provision_attempts = self._max_retries
        await self._session.flush()
        await self._update_track(sub, FulfillmentStatus.IN_PROGRESS, OverallStatus.PENDING, error_message=sub.last_provider_error)
        return "needs_input"

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _next_retry(self, sub) -> Optional[datetime]:
        if sub.provision_attempts >= self._max_retries:
            sub.needs_review = True
            return None
        return datetime.now(timezone.utc) + _backoff_delay(sub.provision_attempts)

    async def _service_for(self, slug: str) -> Optional[TechnologyServiceEntity]:
        result = await self._session.execute(
            select(TechnologyServiceEntity).where(
                TechnologyServiceEntity.slug == slug,
                TechnologyServiceEntity.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def _user_for(self, user_id: str) -> Optional[AppUser]:
        try:
            result = await self._session.execute(select(AppUser).where(AppUser.id == uuid.UUID(str(user_id))))
            return result.scalar_one_or_none()
        except Exception:
            return None

    @staticmethod
    def _subscription_metadata(sub) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        if sub.provision_input:
            try:
                stored = json.loads(sub.provision_input)
                if isinstance(stored, dict):
                    meta.update(stored)
            except Exception:
                pass
        return meta

    async def _update_track(
        self,
        sub,
        fulfillment_status: str,
        overall_status: str,
        *,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        try:
            from app.repository.track_record_repository import TrackRecordRepository

            repo = TrackRecordRepository(self._session)
            record = None
            if sub.razorpay_payment_id:
                record = await repo.find_by_razorpay_payment_id(sub.razorpay_payment_id)
            if record is None and sub.razorpay_order_id:
                record = await repo.find_by_razorpay_order_id(sub.razorpay_order_id)
            if record is None:
                logger.warning("technology.retry.no_track_record sub=%s", sub.id)
                return
            await self._track_service.record_paid_attempt(
                internal_order_id=record.internal_order_id,
                category=record.category or TrackRecordCategory.TECHNOLOGY_PURCHASE,
                provider_subcategory="ResellPortal",
                item_name=record.item_name or sub.service_name,
                amount_charged=float(record.amount_charged or 0.0),
                payment_status=PaymentStatus.CAPTURED,
                razorpay_order_id=record.razorpay_order_id,
                razorpay_payment_id=record.razorpay_payment_id,
                fulfillment_status=fulfillment_status,
                overall_status=overall_status,
                error_code=error_code,
                error_message=error_message,
                error_source="RESELLPORTAL_OR_BACKEND" if error_code else None,
                clear_errors=True,
            )
        except Exception:
            logger.exception("technology.retry.track_update_failed sub=%s", sub.id)

    async def _send_confirmation_email(self, sub, user_email: str) -> None:
        if sub.confirmation_sent:
            return
        try:
            plan_name = sub.plan_code.replace("_", " ").title()
            await MailService.send_technology_purchase_confirmation_email(
                to_email=user_email,
                customer_name=user_email,
                service_name=sub.service_name,
                plan_name=plan_name,
                billing_cycle=sub.billing_cycle,
                cobrother_order_id=str(sub.id),
                razorpay_payment_id=sub.razorpay_payment_id,
                amount_inr=float(sub.price or 0.0),
                purchase_date=datetime.now(timezone.utc).strftime("%d %b %Y"),
                service_status="Active",
                provider_info=(
                    f"Service ID: {sub.provider_subscription_id or sub.provider_order_id or 'N/A'}"
                ),
                purchases_url=f"{settings.FRONTEND_BASE_URL.rstrip('/')}/purchases",
            )
            sub.email_sent = True
            sub.confirmation_sent = True
            await self._session.flush()
        except Exception:
            logger.exception("technology.retry.confirmation_email.failed sub=%s", sub.id)

    async def _send_pending_email(self, sub, user_email: str, *, needs_input: bool) -> None:
        if sub.email_sent:
            return
        try:
            reason = (
                "Additional information is required to activate this service. "
                f"{sub.last_provider_error or ''} Your payment is safe — no further charge will be made."
                if needs_input
                else (
                    "Automatic activation is in progress and will be retried shortly. "
                    "You will receive a confirmation email once your service is active."
                )
            )
            await MailService.send_technology_purchase_pending_email(
                to_email=user_email,
                customer_name=user_email,
                service_name=sub.service_name,
                plan_name=sub.plan_code.replace("_", " ").title(),
                billing_cycle=sub.billing_cycle,
                cobrother_order_id=str(sub.id),
                razorpay_payment_id=sub.razorpay_payment_id,
                amount_inr=float(sub.price or 0.0),
                purchase_date=datetime.now(timezone.utc).strftime("%d %b %Y"),
                reason=reason,
                purchases_url=f"{settings.FRONTEND_BASE_URL.rstrip('/')}/purchases",
            )
            sub.email_sent = True
            await self._session.flush()
        except Exception:
            logger.exception("technology.retry.pending_email.failed sub=%s", sub.id)

    async def _send_failed_email(self, sub, user_email: str) -> None:
        if sub.email_sent:
            return
        try:
            await MailService.send_technology_purchase_failed_email(
                to_email=user_email,
                customer_name=user_email,
                service_name=sub.service_name,
                plan_name=sub.plan_code.replace("_", " ").title(),
                billing_cycle=sub.billing_cycle,
                cobrother_order_id=str(sub.id),
                razorpay_payment_id=sub.razorpay_payment_id,
                amount_inr=float(sub.price or 0.0),
                purchase_date=datetime.now(timezone.utc).strftime("%d %b %Y"),
                reason=sub.last_provider_error or "Provider provisioning failed.",
                purchases_url=f"{settings.FRONTEND_BASE_URL.rstrip('/')}/purchases",
            )
            sub.email_sent = True
            await self._session.flush()
        except Exception:
            logger.exception("technology.retry.failed_email.failed sub=%s", sub.id)
