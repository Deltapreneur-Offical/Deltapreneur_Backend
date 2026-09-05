"""HubRegistrar service-fee workflow (Java FeeController + AdminService fee methods)."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.database import SessionLocal
from app.core.exceptions import AppException
from app.entity.cobrother.cobrother_request_entity import CoBrotherRequest
from app.entity.user.app_user import AppUser
from app.integrations.razorpay import client as rzp
from app.repository.cobrother_request_repository import CoBrotherRequestRepository
from app.service.cobrother.cobrother_request_mail import notify_cobrother_assigned_async
from app.utils.marketplace_enums import CoBrotherRequestStatus

logger = logging.getLogger(__name__)

FEE_INR = 1000.0


def _serialize_fee_request(row: CoBrotherRequest) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "requestType": row.request_type.value if row.request_type else None,
        "entityId": str(row.entity_id),
        "status": row.status.value if row.status else None,
        "listerId": str(row.lister_id) if row.lister_id else None,
        "razorpayOrderId": row.razorpay_order_id,
        "razorpayPaymentId": row.razorpay_payment_id,
        "assignedHubRegistrarId": str(row.assigned_cobrother_id) if row.assigned_cobrother_id else None,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


class FeeService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = CoBrotherRequestRepository(session)

    async def list_my_requests(self, lister: AppUser) -> list[dict[str, Any]]:
        rows: Sequence[CoBrotherRequest] = await self._repo.list_payment_pending_for_lister(lister.id)
        return [_serialize_fee_request(r) for r in rows]

    async def create_order(self, request_id: uuid.UUID, *, lister: AppUser) -> dict[str, Any]:
        row = await self._repo.get_by_id(request_id)
        if row is None:
            raise AppException("Request not found.", status_code=404)
        if row.lister_id != lister.id:
            raise AppException("Not your request.", status_code=403)
        if row.status != CoBrotherRequestStatus.PAYMENT_PENDING:
            raise AppException("Payment already processed or invalid state.", status_code=400)
        if not rzp.is_configured():
            raise AppException("Payment gateway is not configured.", status_code=503)
        receipt = f"cbr_{str(request_id).replace('-', '')[:16]}"
        try:
            order = rzp.create_order(
                amount_inr=FEE_INR,
                receipt=receipt,
                notes={"feeRequestId": str(request_id), "listerId": str(lister.id)},
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("fee.create_order.failed request=%s", request_id)
            raise AppException("Order creation failed.", status_code=502) from exc
        row.razorpay_order_id = order["id"]
        await self._repo.save(row)
        await self._session.commit()
        return {
            "orderId": order["id"],
            "amount": FEE_INR,
            "currency": "INR",
            "requestId": str(request_id),
            "keyId": rzp.get_key_id(),
        }

    async def verify(
        self,
        request_id: uuid.UUID,
        *,
        razorpay_payment_id: str,
        razorpay_order_id: str,
        razorpay_signature: str,
        lister: AppUser,
    ) -> dict[str, Any]:
        row = await self._repo.get_by_id(request_id)
        if row is None:
            raise AppException("Request not found.", status_code=404)
        if row.lister_id != lister.id:
            raise AppException("Not your request.", status_code=403)
        if not rzp.verify_payment_signature(razorpay_order_id, razorpay_payment_id, razorpay_signature):
            raise AppException("Payment verification failed.", status_code=400)
        row.razorpay_payment_id = razorpay_payment_id
        row.status = CoBrotherRequestStatus.FORWARDED
        await self._repo.save(row)
        await self._session.commit()

        sync_db = SessionLocal()
        try:
            loaded = (
                sync_db.query(CoBrotherRequest)
                .options(
                    joinedload(CoBrotherRequest.lister),
                    joinedload(CoBrotherRequest.assigned_cobrother),
                )
                .filter(CoBrotherRequest.id == request_id)
                .first()
            )
            if loaded and loaded.assigned_cobrother:
                await notify_cobrother_assigned_async(
                    sync_db,
                    cobrother=loaded.assigned_cobrother,
                    row=loaded,
                )
        finally:
            sync_db.close()

        return {"success": True, "message": "Payment verified, Deltapreneur notified"}

    async def cancel(self, request_id: uuid.UUID, *, lister: AppUser) -> dict[str, Any]:
        row = await self._repo.get_by_id(request_id)
        if row is None:
            raise AppException("Request not found.", status_code=404)
        if row.lister_id != lister.id:
            raise AppException("Not your request.", status_code=403)
        if row.status != CoBrotherRequestStatus.PAYMENT_PENDING:
            raise AppException("Cannot cancel at this stage.", status_code=400)
        row.status = CoBrotherRequestStatus.CANCELLED
        await self._repo.save(row)
        await self._session.commit()
        return {"success": True}
