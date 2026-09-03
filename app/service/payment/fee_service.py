"""Compatibility fee workflow backed by auction participation records."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.auction.auction_participation_entity import AuctionParticipationStatus
from app.entity.user.app_user import AppUser
from app.integrations.razorpay import client as rzp
from app.repository.auction_participation_repository import AuctionParticipationRepository


class FeeService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._rows = AuctionParticipationRepository(session)

    async def list_my_requests(self, user: AppUser) -> dict:
        items = await self._rows.list_by_user(user.id)
        return {
            "requests": [
                {
                    "id": str(row.id),
                    "auctionType": row.auction_type.value,
                    "auctionId": str(row.auction_id),
                    "amountInr": row.fee_amount_inr,
                    "status": row.status.value,
                    "orderId": row.razorpay_order_id,
                    "paymentId": row.razorpay_payment_id,
                }
                for row in items
            ]
        }

    async def create_order(self, request_id: str, user: AppUser) -> dict:
        row = await self._get_owned_request(request_id, user)
        if row.status == AuctionParticipationStatus.COMPLETED:
            raise AppException("Participation fee already paid.", status_code=409)

        try:
            rzp_order = rzp.create_order(
                amount_inr=row.fee_amount_inr,
                receipt=f"fee_req_{row.id}"[:40],
                notes={
                    "requestId": str(row.id),
                    "auctionId": str(row.auction_id),
                    "auctionType": row.auction_type.value,
                },
            )
        except ValueError as exc:
            raise AppException(str(exc), status_code=400) from exc
        except RuntimeError as exc:
            raise AppException(str(exc), status_code=500) from exc
        except Exception as exc:  # noqa: BLE001
            raise AppException("Unable to create fee order right now.", status_code=500) from exc

        row.razorpay_order_id = rzp_order["id"]
        row.status = AuctionParticipationStatus.CREATED
        await self._rows.save(row)
        await self._session.commit()

        return {
            "success": True,
            "requestId": str(row.id),
            "orderId": rzp_order["id"],
            "amount": row.fee_amount_inr,
            "currency": "INR",
            "keyId": rzp.get_key_id(),
        }

    async def verify(
        self,
        request_id: str,
        user: AppUser,
        *,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> dict:
        row = await self._get_owned_request(request_id, user)
        if row.razorpay_order_id != razorpay_order_id:
            raise AppException("Order mismatch for this fee request.", status_code=400)
        if not rzp.verify_payment_signature(
            razorpay_order_id,
            razorpay_payment_id,
            razorpay_signature,
        ):
            raise AppException("Invalid payment signature.", status_code=400)

        row.status = AuctionParticipationStatus.COMPLETED
        row.razorpay_payment_id = razorpay_payment_id
        await self._rows.save(row)
        await self._session.commit()
        return {"success": True, "requestId": str(row.id), "paid": True}

    async def cancel(self, request_id: str, user: AppUser) -> dict:
        row = await self._get_owned_request(request_id, user)
        if row.status == AuctionParticipationStatus.COMPLETED:
            raise AppException("Completed fee request cannot be cancelled.", status_code=409)

        row.status = AuctionParticipationStatus.FAILED
        await self._rows.save(row)
        await self._session.commit()
        return {"success": True, "requestId": str(row.id), "status": row.status.value}

    async def _get_owned_request(self, request_id: str, user: AppUser):
        try:
            req_id = uuid.UUID(str(request_id))
        except ValueError as exc:
            raise AppException("Invalid request id.", status_code=400) from exc

        row = await self._rows.get_by_id(req_id)
        if row is None:
            raise AppException("Fee request not found.", status_code=404)
        if row.user_id != user.id:
            raise AppException("Not authorized for this fee request.", status_code=403)
        return row
