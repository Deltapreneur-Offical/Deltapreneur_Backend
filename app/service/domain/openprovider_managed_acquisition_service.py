"""OpenProvider managed acquisition CRM (admin + notify buyer)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.core.exceptions import AppException
from app.entity.domain.openprovider_managed_acquisition_entity import (
    OpenProviderManagedAcquisition,
)
from app.entity.notification.notification_type import NotificationType
from app.entity.user.app_user import AppUser
from app.repository.openprovider_managed_acquisition_repository import (
    OpenProviderManagedAcquisitionRepository,
)
from app.service.auth.mail_service import MailService
from app.service.domain.managed_acquisition_serializers import (
    serialize_op_managed_acquisition,
)
from app.service.notification.notification_service import NotificationService
from app.utils.marketplace_enums import DomainEnquiryStatus

logger = logging.getLogger(__name__)

_ALLOWED_TRANSITIONS: dict[DomainEnquiryStatus, set[DomainEnquiryStatus]] = {
    DomainEnquiryStatus.PENDING: {
        DomainEnquiryStatus.IN_PROGRESS,
        DomainEnquiryStatus.ACCEPTED,
        DomainEnquiryStatus.DECLINED,
    },
    DomainEnquiryStatus.IN_PROGRESS: {
        DomainEnquiryStatus.ACCEPTED,
        DomainEnquiryStatus.DECLINED,
    },
    DomainEnquiryStatus.ACCEPTED: {
        DomainEnquiryStatus.COMPLETED,
        DomainEnquiryStatus.DECLINED,
    },
    DomainEnquiryStatus.COMPLETED: set(),
    DomainEnquiryStatus.DECLINED: {
        DomainEnquiryStatus.PENDING,
    },
}

_UPDATABLE = {
    DomainEnquiryStatus.PENDING,
    DomainEnquiryStatus.IN_PROGRESS,
    DomainEnquiryStatus.ACCEPTED,
    DomainEnquiryStatus.COMPLETED,
    DomainEnquiryStatus.DECLINED,
}


class OpenProviderManagedAcquisitionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = OpenProviderManagedAcquisitionRepository(session)

    @staticmethod
    def _parse_status(value: str) -> DomainEnquiryStatus:
        normalized = (value or "").strip().upper()
        try:
            status = DomainEnquiryStatus(normalized)
        except ValueError as exc:
            raise AppException(
                f"Invalid status '{value}'.",
                status_code=400,
            ) from exc
        if status not in _UPDATABLE:
            raise AppException(
                f"Status '{status.value}' cannot be set via this endpoint.",
                status_code=400,
            )
        return status

    async def list_all_admin(self) -> list[dict[str, Any]]:
        rows = await self._repo.list_all_admin()
        return [serialize_op_managed_acquisition(r) for r in rows]

    async def update_status(
        self,
        acquisition_id: uuid.UUID,
        *,
        admin: AppUser,
        status: str,
        admin_notes: str | None = None,
    ) -> dict[str, Any]:
        new_status = self._parse_status(status)
        row = await self._repo.get_by_id(acquisition_id)
        if row is None:
            raise AppException("Acquisition request not found.", status_code=404)

        try:
            current = DomainEnquiryStatus(row.status)
        except ValueError as exc:
            raise AppException(
                f"Invalid current status '{row.status}'.",
                status_code=400,
            ) from exc

        allowed = _ALLOWED_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            raise AppException(
                f"Transition not allowed from {current.value} to {new_status.value}.",
                status_code=400,
            )

        row.status = new_status.value
        if admin_notes is not None:
            row.admin_notes = admin_notes.strip() or None

        now = datetime.now(timezone.utc)
        if new_status == DomainEnquiryStatus.IN_PROGRESS:
            row.in_progress_at = now
        elif new_status == DomainEnquiryStatus.ACCEPTED:
            row.accepted_at = now
        elif new_status == DomainEnquiryStatus.COMPLETED:
            row.completed_at = now
        elif new_status == DomainEnquiryStatus.DECLINED:
            row.declined_at = now

        await self._repo.save(row)
        await self._session.commit()
        await self._session.refresh(row)

        await self._notify_buyer(
            row,
            status_label=new_status.value.replace("_", " ").title(),
            admin_message=(admin_notes.strip() if admin_notes else None) or None,
        )
        return serialize_op_managed_acquisition(row)

    async def remove(
        self,
        acquisition_id: uuid.UUID,
        *,
        admin: AppUser,
        admin_notes: str | None = None,
    ) -> dict[str, Any]:
        row = await self._repo.get_by_id(acquisition_id)
        if row is None:
            raise AppException("Acquisition request not found.", status_code=404)
        now = datetime.now(timezone.utc)
        row.is_deleted = True
        row.deleted_at = now
        row.deleted_by = admin.id
        if admin_notes is not None:
            row.admin_notes = admin_notes.strip() or row.admin_notes
        await self._repo.save(row)
        await self._session.commit()
        return {"success": True, "id": str(row.id)}

    async def _notify_buyer(
        self,
        row: OpenProviderManagedAcquisition,
        *,
        status_label: str,
        admin_message: str | None,
    ) -> None:
        fqdn = f"{row.domain_name}.{row.tld.lstrip('.')}" if row.tld else row.domain_name
        if "." in row.domain_name:
            fqdn = row.domain_name
        to_email = (row.email or "").strip()
        buyer_name = row.full_name or "there"

        if row.user_id:
            buyer = await self._session.get(AppUser, row.user_id)
            if buyer and buyer.email:
                to_email = buyer.email.strip() or to_email
                if not buyer_name or buyer_name == "there":
                    buyer_name = f"{buyer.firstname or ''} {buyer.lastname or ''}".strip() or buyer_name

        if to_email:
            try:
                await MailService.send_premium_marketplace_buyer_update_email(
                    to_email=to_email,
                    buyer_name=buyer_name,
                    domain_fqdn=fqdn,
                    status_label=status_label,
                    admin_message=admin_message,
                    enquiry_id=str(row.id),
                )
            except Exception:
                logger.exception("op_managed.buyer_update_email.failed id=%s", row.id)

        if row.user_id:
            db = SessionLocal()
            try:
                user = db.query(AppUser).filter(AppUser.id == row.user_id).first()
                if user is not None:
                    note = (admin_message or "").strip()
                    message = f"Status: {status_label}." + (f" Message: {note}" if note else "")
                    NotificationService.notify(
                        db,
                        user=user,
                        notification_type=NotificationType.DOMAIN_PREMIUM_UPDATE,
                        title=f"Update on {fqdn}",
                        message=message[:500],
                        target_url="/domains/dashboard?tab=acquisitions",
                    )
                    db.commit()
            except Exception:
                logger.exception("op_managed.buyer_update_notify.failed id=%s", row.id)
                db.rollback()
            finally:
                db.close()
