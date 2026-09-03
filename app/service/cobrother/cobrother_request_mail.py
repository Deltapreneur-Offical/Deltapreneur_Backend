"""CoBrother request email helpers (Java MailService parity)."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import settings
from app.utils.run_async import run_async_from_sync
from app.entity.cobrother.cobrother_request_entity import CoBrotherRequest
from app.entity.notification.notification_type import NotificationType
from app.entity.user.app_user import AppUser
from app.service.auth.mail_service import MailService
from app.service.notification.notification_service import NotificationService

logger = logging.getLogger(__name__)


def _fee_requests_url() -> str:
    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}/fee-requests"


def _cobrother_dashboard_url() -> str:
    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}/cobrother"


def _display_name(user: AppUser | None) -> str:
    if user is None:
        return "—"
    parts = [user.firstname or "", user.lastname or ""]
    name = " ".join(p for p in parts if p).strip()
    return name or user.email or "—"


def _parse_snapshot(snapshot: str | None) -> dict[str, Any]:
    if not snapshot:
        return {}
    try:
        data = json.loads(snapshot)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return {}


def _entity_title(row: CoBrotherRequest) -> str:
    data = _parse_snapshot(row.entity_snapshot)
    title = data.get("title")
    if title:
        return str(title)
    return str(row.entity_id)


async def _send_fee_request_email_async(
    *,
    lister: AppUser,
    entity_title: str,
) -> None:
    if not settings.mail_configured():
        logger.warning("mail.skip fee_request lister=%s mail not configured", lister.email)
        return
    await MailService.send_cobrother_fee_request_email(
        to_email=lister.email,
        lister_name=_display_name(lister),
        entity_title=entity_title,
        payment_url=_fee_requests_url(),
    )


async def _send_assignment_email_async(
    *,
    cobrother: AppUser,
    row: CoBrotherRequest,
) -> None:
    if not settings.mail_configured():
        logger.warning(
            "mail.skip assignment cobrother=%s mail not configured",
            cobrother.email,
        )
        return
    data = _parse_snapshot(row.entity_snapshot)
    lister = row.lister
    await MailService.send_cobrother_assignment_email(
        to_email=cobrother.email,
        cobrother_name=_display_name(cobrother),
        request_type=row.request_type.value if row.request_type else "REQUEST",
        entity_title=_entity_title(row),
        lister_name=data.get("listerName") or _display_name(lister),
        lister_email=data.get("listerEmail") or (lister.email if lister else None),
        lister_phone=data.get("listerPhone") or (lister.phone_number if lister else None),
        applicant_name=data.get("applicantName"),
        applicant_email=data.get("applicantEmail"),
        applicant_phone=data.get("applicantPhone"),
        dashboard_url=_cobrother_dashboard_url(),
    )


def send_fee_request_email(*, lister: AppUser, entity_title: str) -> None:
    try:
        run_async_from_sync(
            _send_fee_request_email_async,
            lister=lister,
            entity_title=entity_title,
        )
    except Exception:  # noqa: BLE001
        logger.exception("fee_request.email.failed lister=%s", lister.email)


def notify_cobrother_assigned(
    db,
    *,
    cobrother: AppUser,
    row: CoBrotherRequest,
) -> None:
    title = _entity_title(row)
    try:
        NotificationService.notify(
            db,
            cobrother,
            NotificationType.COVENTURE_APPLICATION_RECEIVED,
            title="New Request Assigned",
            message=f"You have been assigned a HubRegistrar request for {title}.",
            target_url="/cobrother",
        )
    except Exception:  # noqa: BLE001
        logger.exception("forward.notify_cobrother.failed cobrother_id=%s", cobrother.id)

    try:
        run_async_from_sync(
            _send_assignment_email_async,
            cobrother=cobrother,
            row=row,
        )
    except Exception:  # noqa: BLE001
        logger.exception("assignment.email.failed cobrother=%s", cobrother.email)


async def notify_cobrother_assigned_async(
    db,
    *,
    cobrother: AppUser,
    row: CoBrotherRequest,
) -> None:
    title = _entity_title(row)
    try:
        NotificationService.notify(
            db,
            cobrother,
            NotificationType.COVENTURE_APPLICATION_RECEIVED,
            title="New Request Assigned",
            message=f"You have been assigned a HubRegistrar request for {title}.",
            target_url="/cobrother",
        )
    except Exception:  # noqa: BLE001
        logger.exception("forward.notify_cobrother.failed cobrother_id=%s", cobrother.id)

    try:
        await _send_assignment_email_async(cobrother=cobrother, row=row)
    except Exception:  # noqa: BLE001
        logger.exception("assignment.email.failed cobrother=%s", cobrother.email)
