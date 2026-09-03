"""Domain registration order data access."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
from app.utils.registration_enums import RegistrationOrderStatus


class DomainRegistrationOrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, order: DomainRegistrationOrder) -> DomainRegistrationOrder:
        from app.service.domain.tax_invoice_number_service import ensure_tax_invoice_number

        await ensure_tax_invoice_number(self._session, order)
        self._session.add(order)
        await self._session.flush()
        await self._session.refresh(order)
        return order

    async def save(self, order: DomainRegistrationOrder) -> DomainRegistrationOrder:
        from app.service.domain.tax_invoice_number_service import ensure_tax_invoice_number

        await ensure_tax_invoice_number(self._session, order)
        await self._session.flush()
        await self._session.refresh(order)
        return order

    async def get_by_id(self, order_id: uuid.UUID) -> Optional[DomainRegistrationOrder]:
        stmt = select(DomainRegistrationOrder).where(DomainRegistrationOrder.id == order_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, order_id: uuid.UUID) -> Optional[DomainRegistrationOrder]:
        stmt = (
            select(DomainRegistrationOrder)
            .where(DomainRegistrationOrder.id == order_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_razorpay_order_id(
        self, razorpay_order_id: str,
    ) -> Optional[DomainRegistrationOrder]:
        stmt = select(DomainRegistrationOrder).where(
            DomainRegistrationOrder.razorpay_order_id == razorpay_order_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_razorpay_order_id(
        self, razorpay_order_id: str,
    ) -> Sequence[DomainRegistrationOrder]:
        stmt = (
            select(DomainRegistrationOrder)
            .where(DomainRegistrationOrder.razorpay_order_id == razorpay_order_id)
            .order_by(DomainRegistrationOrder.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_razorpay_payment_id(
        self, razorpay_payment_id: str,
    ) -> Sequence[DomainRegistrationOrder]:
        stmt = (
            select(DomainRegistrationOrder)
            .where(DomainRegistrationOrder.razorpay_payment_id == razorpay_payment_id)
            .order_by(DomainRegistrationOrder.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_by_openprovider_domain_id(
        self, open_provider_domain_id: str,
    ) -> Optional[DomainRegistrationOrder]:
        stmt = select(DomainRegistrationOrder).where(
            DomainRegistrationOrder.open_provider_domain_id == open_provider_domain_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_openprovider_domain_id(
        self, open_provider_domain_id: str,
    ) -> Sequence[DomainRegistrationOrder]:
        stmt = (
            select(DomainRegistrationOrder)
            .where(
                DomainRegistrationOrder.open_provider_domain_id == open_provider_domain_id,
            )
            .order_by(DomainRegistrationOrder.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_active_by_domain(
        self,
        domain_name: str,
        domain_extension: str,
    ) -> Optional[DomainRegistrationOrder]:
        stmt = select(DomainRegistrationOrder).where(
            DomainRegistrationOrder.domain_name == domain_name,
            DomainRegistrationOrder.domain_extension == domain_extension,
            DomainRegistrationOrder.status.in_([
                RegistrationOrderStatus.ACTIVE,
                RegistrationOrderStatus.REGISTRATION_PENDING,
                RegistrationOrderStatus.PAYMENT_COMPLETED,
            ]),
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def list_by_buyer(self, buyer_id: uuid.UUID) -> Sequence[DomainRegistrationOrder]:
        stmt = (
            select(DomainRegistrationOrder)
            .where(DomainRegistrationOrder.buyer_id == buyer_id)
            .order_by(DomainRegistrationOrder.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_active_transfer_by_buyer_and_domain(
        self,
        buyer_id: uuid.UUID,
        domain_name: str,
        domain_extension: str,
    ) -> Optional[DomainRegistrationOrder]:
        """Return the most-recent non-terminal transfer order for this buyer+domain.

        Used by create_transfer_payment_order to prevent duplicate DB rows when
        the user clicks the form multiple times or the checkout modal is dismissed.
        """
        _terminal = [
            RegistrationOrderStatus.REFUNDED,
        ]
        stmt = (
            select(DomainRegistrationOrder)
            .where(
                DomainRegistrationOrder.buyer_id == buyer_id,
                DomainRegistrationOrder.domain_name == domain_name,
                DomainRegistrationOrder.domain_extension == domain_extension,
                DomainRegistrationOrder.transfer_status != "NONE",
                DomainRegistrationOrder.status.notin_(_terminal),
            )
            .order_by(DomainRegistrationOrder.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def list_by_status(
        self, status: RegistrationOrderStatus,
    ) -> Sequence[DomainRegistrationOrder]:
        stmt = select(DomainRegistrationOrder).where(DomainRegistrationOrder.status == status)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_provision_retry_candidates(
        self,
        *,
        max_attempts: int,
    ) -> Sequence[DomainRegistrationOrder]:
        stmt = select(DomainRegistrationOrder).where(
            DomainRegistrationOrder.status.in_([
                RegistrationOrderStatus.PAYMENT_COMPLETED,
                RegistrationOrderStatus.REGISTRATION_PENDING,
                RegistrationOrderStatus.PROVISION_FAILED,
            ]),
            DomainRegistrationOrder.provision_attempts < max_attempts,
            # Domain transfers never enter the registration provision/retry
            # pipeline (provision_order refuses them by design).
            DomainRegistrationOrder.transfer_status == "NONE",
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_stale_unpaid(self, before: datetime) -> Sequence[DomainRegistrationOrder]:
        stmt = select(DomainRegistrationOrder).where(
            DomainRegistrationOrder.status == RegistrationOrderStatus.CREATED,
            DomainRegistrationOrder.created_at < before,
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_pending_reconcile_candidates(
        self,
        *,
        limit: int = 25,
    ) -> Sequence[DomainRegistrationOrder]:
        stmt = (
            select(DomainRegistrationOrder)
            .where(
                DomainRegistrationOrder.status
                == RegistrationOrderStatus.REGISTRATION_PENDING,
                DomainRegistrationOrder.open_provider_domain_id.isnot(None),
            )
            .order_by(DomainRegistrationOrder.updated_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_transfer_reconcile_candidates(
        self,
        *,
        limit: int = 20,
    ) -> Sequence[DomainRegistrationOrder]:
        """Paid domain transfers whose provider submission never completed.

        status=PAYMENT_COMPLETED + transfer_status=PENDING + a captured payment
        + no OpenProvider domain id means the registrar was unreachable when the
        transfer was submitted (Case: provider temporarily unavailable). The
        reconcile worker retries the submission safely; a provider rejection
        moves the order to PROVISION_FAILED so it drops out of this set.
        """
        stmt = (
            select(DomainRegistrationOrder)
            .where(
                DomainRegistrationOrder.status
                == RegistrationOrderStatus.PAYMENT_COMPLETED,
                DomainRegistrationOrder.transfer_status == "PENDING",
                DomainRegistrationOrder.razorpay_payment_id.isnot(None),
                DomainRegistrationOrder.open_provider_domain_id.is_(None),
            )
            .order_by(DomainRegistrationOrder.updated_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_stale_pending(
        self,
        *,
        cutoff: datetime,
        limit: int = 50,
    ) -> Sequence[DomainRegistrationOrder]:
        """Orders stuck in pending/payment-completed older than cutoff (by created_at)."""
        stmt = (
            select(DomainRegistrationOrder)
            .where(
                DomainRegistrationOrder.status.in_([
                    RegistrationOrderStatus.REGISTRATION_PENDING,
                    RegistrationOrderStatus.PAYMENT_COMPLETED,
                ]),
                DomainRegistrationOrder.created_at < cutoff,
                # Domain transfers are never "stuck registration" alerts.
                DomainRegistrationOrder.transfer_status == "NONE",
            )
            .order_by(DomainRegistrationOrder.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_open_pending(
        self,
        *,
        limit: int = 50,
    ) -> Sequence[DomainRegistrationOrder]:
        """All REGISTRATION_PENDING / PAYMENT_COMPLETED rows (recovery filters by stamp)."""
        stmt = (
            select(DomainRegistrationOrder)
            .where(
                DomainRegistrationOrder.status.in_([
                    RegistrationOrderStatus.REGISTRATION_PENDING,
                    RegistrationOrderStatus.PAYMENT_COMPLETED,
                ]),
                # Domain transfers are never candidates for the registration
                # stale-pending failure pipeline.
                DomainRegistrationOrder.transfer_status == "NONE",
            )
            .order_by(DomainRegistrationOrder.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_all(
        self, *, status: Optional[RegistrationOrderStatus] = None,
    ) -> Sequence[DomainRegistrationOrder]:
        stmt = select(DomainRegistrationOrder).order_by(
            DomainRegistrationOrder.created_at.desc(),
        )
        if status is not None:
            stmt = stmt.where(DomainRegistrationOrder.status == status)
        result = await self._session.execute(stmt)
        return result.scalars().all()
