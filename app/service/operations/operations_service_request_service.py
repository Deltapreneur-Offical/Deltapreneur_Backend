"""Operations hire/booking request business logic."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

import logging

from app.core.exceptions import AppException
from app.entity.operations.operations_service_request_entity import OperationsServiceRequest
from app.entity.user.app_user import AppUser
from app.model.operations.operations_service_request_dto import (
    OperationsPaymentOrderBody,
    OperationsPaymentVerifyBody,
    OperationsServiceRequestCreateBody,
    OperationsServiceRequestStatusBody,
)
from app.model.operations.operations_service_request_mapper import (
    build_operations_service_request_response,
)
from app.repository.operations_service_repository import OperationsServiceRepository
from app.repository.operations_service_request_repository import (
    OperationsServiceRequestRepository,
)
from app.integrations.razorpay import client as rzp
from app.utils.field_validators import normalize_profile_phone

logger = logging.getLogger(__name__)


def _derive_request_meta(service_type: str) -> tuple[str, str]:
    normalized = (service_type or "virtual_assistance").strip().lower()
    if normalized == "compliance":
        return "booking", "one_time"
    return "hire", "monthly"


class OperationsServiceRequestService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = OperationsServiceRequestRepository(session)
        self._services = OperationsServiceRepository(session)

    # ── Razorpay order creation ───────────────────────────────────────────

    async def create_payment_order(
        self,
        body: "OperationsPaymentOrderBody",
        *,
        user: AppUser,
    ) -> dict:
        """Validate form, create a pending request, and return Razorpay order data."""
        try:
            service_id = uuid.UUID(body.operations_service_id)
        except ValueError:
            raise AppException("Invalid operations service id.", status_code=400)

        service = await self._services.get_by_id(service_id, public_only=True)
        if service is None:
            raise AppException("Operations service not found.", status_code=404)

        # Check for existing pending request
        existing = await self._repo.find_pending_for_user_service(
            user_id=user.id, operations_service_id=service_id,
        )
        if existing and existing.razorpay_order_id and existing.payment_status == "PENDING":
            # Reuse existing unpaid order — return its Razorpay order data
            order = rzp.fetch_order(existing.razorpay_order_id)
            return {
                "requestId": str(existing.id),
                "orderId": order["id"],
                "amount": order["amount"],
                "currency": order.get("currency", "INR"),
                "keyId": rzp.get_key_id(),
            }
        if existing and existing.payment_status == "SUCCESS":
            raise AppException(
                "You already have a confirmed booking for this service.",
                status_code=400,
            )
        # Delete stale pending request if it exists but has no order
        if existing:
            await self._repo.delete(existing)

        request_type, billing_period = _derive_request_meta(service.service_type)
        phone = self._normalize_phone(body.phone)

        # Authoritative price from database
        amount_inr = float(service.price or 0)
        if amount_inr <= 0:
            raise AppException(
                "This service does not have a configured price.",
                status_code=400,
            )

        # Create pending request record
        row = OperationsServiceRequest(
            operations_service_id=service_id,
            user_id=user.id,
            request_type=request_type,
            service_type=service.service_type,
            billing_period=billing_period,
            service_name=service.name,
            quoted_price=amount_inr,
            full_name=body.full_name.strip(),
            email=body.email.strip(),
            phone=phone,
            company_name=body.company_name,
            city_state=body.city_state,
            message=body.message,
            preferred_timeline=body.preferred_timeline,
            status="PENDING",
            payment_status="PENDING",
            payment_amount_inr=amount_inr,
        )
        await self._repo.create(row)
        await self._session.flush()

        # Create Razorpay order
        try:
            rzp_order = rzp.create_order(
                amount_inr=amount_inr,
                receipt=f"ops_req_{str(row.id)[:20]}",
                notes={
                    "type": "hub_registrar_booking",
                    "requestId": str(row.id),
                    "serviceId": str(service_id),
                    "serviceName": service.name,
                    "buyerId": str(user.id),
                },
            )
        except Exception as exc:
            logger.exception("razorpay.create_order.failed request=%s", row.id)
            raise AppException(
                "Could not create payment order. Please try again.",
                status_code=502,
            ) from exc

        row.razorpay_order_id = rzp_order["id"]
        await self._repo.save(row)
        await self._session.commit()

        logger.info(
            "hubregistrar.payment_order_created request=%s service=%s amount=%s rzp_order=%s",
            row.id, service.name, amount_inr, rzp_order["id"],
        )

        return {
            "requestId": str(row.id),
            "orderId": rzp_order["id"],
            "amount": rzp_order["amount"],
            "currency": rzp_order.get("currency", "INR"),
            "keyId": rzp.get_key_id(),
        }

    # ── Razorpay payment verification ──────────────────────────────────────

    async def verify_payment(
        self,
        body: "OperationsPaymentVerifyBody",
        *,
        user: AppUser,
    ) -> dict:
        """Verify Razorpay payment and confirm the booking."""
        try:
            request_id = uuid.UUID(body.request_id)
        except ValueError:
            raise AppException("Invalid request id.", status_code=400)

        row = await self._repo.get_by_id(request_id)
        if row is None:
            raise AppException("Booking request not found.", status_code=404)
        if row.user_id != user.id:
            raise AppException("Unauthorized.", status_code=403)
        if row.payment_status == "SUCCESS":
            # Idempotent — already verified
            return {
                "success": True,
                "message": "Payment already verified.",
                "data": build_operations_service_request_response(row),
            }

        # Verify order matches
        if row.razorpay_order_id and row.razorpay_order_id != body.razorpay_order_id:
            raise AppException("Payment order mismatch.", status_code=400)

        # Verify signature
        if not rzp.verify_payment_signature(
            body.razorpay_order_id,
            body.razorpay_payment_id,
            body.razorpay_signature,
        ):
            row.payment_status = "FAILED"
            row.status = "PAYMENT_FAILED"
            await self._repo.save(row)
            await self._session.commit()
            raise AppException("Payment verification failed.", status_code=400)

        # Verify payment is captured on Razorpay
        try:
            payment = rzp.assert_captured_payment_for_order(
                payment_id=body.razorpay_payment_id,
                order_id=body.razorpay_order_id,
                expected_buyer_id=str(user.id),
            )
        except Exception as exc:
            logger.warning(
                "hubregistrar.payment_verify.capture_check_failed request=%s err=%s",
                row.id, exc,
            )
            row.payment_status = "FAILED"
            row.status = "PAYMENT_FAILED"
            await self._repo.save(row)
            await self._session.commit()
            raise AppException(
                f"Payment could not be confirmed: {exc}", status_code=400,
            ) from exc

        # Mark successful
        row.razorpay_payment_id = body.razorpay_payment_id
        row.razorpay_signature = body.razorpay_signature
        row.payment_status = "SUCCESS"
        row.status = "CONTACT_PENDING"
        row.contact_status = "CONTACT_PENDING"
        await self._repo.save(row)
        await self._session.commit()
        await self._session.refresh(row)

        # Create Track Record for admin audit trail
        try:
            from app.service.platform.track_record_service import (
                TrackRecordService,
                TrackRecordCategory,
            )
            track_svc = TrackRecordService(self._session)
            amount = float(row.payment_amount_inr or row.quoted_price or 0)
            await track_svc.record_paid_attempt(
                internal_order_id=TrackRecordService.generate_internal_order_id("TRK-OPS"),
                category=TrackRecordCategory.OPERATIONS,
                provider_subcategory="HubRegistrar",
                item_name=row.service_name,
                item_id=str(row.id),
                quantity_years=1,
                buyer_name=row.full_name,
                buyer_email=row.email,
                buyer_phone=row.phone,
                buyer_user_id=row.user_id,
                amount_charged=amount,
                currency="INR",
                payment_status="CAPTURED",
                razorpay_order_id=row.razorpay_order_id,
                razorpay_payment_id=row.razorpay_payment_id,
                fulfillment_status="NOT_STARTED",
                overall_status="Success",
                notes=f"Hub Registrar booking: {row.service_name}",
            )
            await self._session.commit()
        except Exception as exc:
            logger.warning(
                "hubregistrar.track_record_failed request=%s err=%s",
                row.id, exc,
            )

        logger.info(
            "hubregistrar.payment_confirmed request=%s service=%s amount=%s payment=%s",
            row.id, row.service_name, row.payment_amount_inr, body.razorpay_payment_id,
        )

        return {
            "success": True,
            "message": "Payment verified and booking confirmed.",
            "data": build_operations_service_request_response(row),
        }

    @staticmethod
    def _normalize_phone(raw: str) -> str:
        try:
            phone = normalize_profile_phone(raw)
        except ValueError as exc:
            raise AppException(str(exc), status_code=400) from exc
        if not phone:
            raise AppException(
                "A valid 10-digit phone number is required.",
                status_code=400,
            )
        return phone

    async def submit(
        self,
        body: OperationsServiceRequestCreateBody,
        *,
        user: AppUser,
    ) -> dict:
        try:
            service_id = uuid.UUID(body.operations_service_id)
        except ValueError as exc:
            raise AppException("Invalid operations service id.", status_code=400) from exc

        service = await self._services.get_by_id(service_id, public_only=True)
        if service is None:
            raise AppException("Operations service not found.", status_code=404)

        existing = await self._repo.find_pending_for_user_service(
            user_id=user.id,
            operations_service_id=service_id,
        )
        if existing:
            raise AppException(
                "You already have a pending request for this service.",
                status_code=400,
            )

        request_type, billing_period = _derive_request_meta(service.service_type)
        phone = self._normalize_phone(body.phone)

        row = OperationsServiceRequest(
            operations_service_id=service_id,
            user_id=user.id,
            request_type=request_type,
            service_type=service.service_type,
            billing_period=billing_period,
            service_name=service.name,
            quoted_price=float(service.price or 0),
            full_name=body.full_name.strip(),
            email=body.email.strip(),
            phone=phone,
            company_name=body.company_name,
            city_state=body.city_state,
            message=body.message,
            preferred_timeline=body.preferred_timeline,
            status="PENDING",
        )
        await self._repo.create(row)
        await self._session.commit()
        await self._session.refresh(row)
        return build_operations_service_request_response(row)

    async def list_for_user(self, *, user: AppUser) -> list[dict]:
        rows = await self._repo.list_for_user(user.id)
        return [build_operations_service_request_response(row) for row in rows]

    async def list_admin(
        self,
        *,
        request_type: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        normalized_type = request_type.strip().lower() if request_type else None
        if normalized_type and normalized_type not in {"hire", "booking"}:
            normalized_type = None
        normalized_status = status.strip().upper() if status else None
        if normalized_status and normalized_status not in {"PENDING", "CONTACTED", "CLOSED"}:
            normalized_status = None
        rows = await self._repo.list_admin(
            request_type=normalized_type,
            status=normalized_status,
        )
        return [build_operations_service_request_response(row) for row in rows]

    async def patch_status_admin(
        self,
        request_id: uuid.UUID,
        body: OperationsServiceRequestStatusBody,
    ) -> dict:
        row = await self._repo.get_by_id(request_id)
        if row is None:
            raise AppException("Operations request not found.", status_code=404)
        row.status = body.status
        # When admin marks as CONTACTED, update contact_status too
        if body.status == "CONTACTED":
            row.contact_status = "CONTACTED"
        await self._repo.save(row)
        await self._session.commit()
        await self._session.refresh(row)
        return build_operations_service_request_response(row)

    async def delete_admin(self, request_id: uuid.UUID) -> None:
        row = await self._repo.get_by_id(request_id)
        if row is None:
            raise AppException("Operations request not found.", status_code=404)
        await self._repo.delete(row)
        await self._session.commit()
