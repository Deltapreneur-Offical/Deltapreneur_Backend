"""Shared add-on catalog and buyer contact helpers."""

from __future__ import annotations

import re
import uuid
from typing import Any, TYPE_CHECKING

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.utils.field_validators import normalize_profile_phone

if TYPE_CHECKING:
    from app.entity.user.app_user import AppUser

ADDON_PRICES: dict[str, float] = {
    "GST_REGISTRATION": 3000,
    "UDYAM_REGISTRATION": 1500,
    "IEC_REGISTRATION": 2000,
    "DIGITAL_SIGNATURE": 3000,
    "PROFESSIONAL_TAX": 2500,
    "STARTUP_INDIA": 3000,
    "VA_ENTRY_ECOMMERCE": 499,
    "VA_MID_ECOMMERCE": 999,
    "VA_EXPERT_ECOMMERCE": 1999,
}


def parse_addon_services(services: list | None) -> tuple[float, str]:
    keys: list[str] = []
    addon_amount = 0.0
    for entry in services or []:
        if isinstance(entry, str):
            key = entry.strip()
            if key:
                keys.append(key)
                addon_amount += float(ADDON_PRICES.get(key, 0))
        elif isinstance(entry, dict):
            key = str(entry.get("key") or entry.get("service") or "").strip()
            if key:
                keys.append(key)
            addon_amount += float(entry.get("price", ADDON_PRICES.get(key, 0)))
    return addon_amount, ",".join(keys)


def resolve_buyer_phone(raw: str | None, user: "AppUser") -> str:
    phone = normalize_profile_phone(raw) or (user.phone_number if user else None)
    if not phone:
        raise AppException(
            "A valid 10-digit phone number is required.",
            status_code=400,
        )
    return phone


def format_phone_display(phone: str | None) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) >= 10:
        return digits[-10:]
    return phone.strip()


def _addon_keys(addon_services: str | list | None) -> list[str]:
    if isinstance(addon_services, str):
        return [k.strip() for k in addon_services.split(",") if k.strip()]

    keys: list[str] = []
    for entry in addon_services or []:
        if isinstance(entry, str):
            key = entry.strip()
        elif isinstance(entry, dict):
            key = str(entry.get("key") or entry.get("service") or "").strip()
        else:
            key = ""
        if key:
            keys.append(key)
    return keys


async def resolve_live_compliance_addon_services(
    session: AsyncSession,
    addon_services: str | list | None,
):
    """Resolve selected cart add-ons from live Delta Registrar compliance services."""
    keys = _addon_keys(addon_services)
    if not keys:
        return []

    from app.entity.operations.operations_service_entity import OperationsService

    service_ids: list[uuid.UUID] = []
    for key in keys:
        try:
            service_ids.append(uuid.UUID(key))
        except (TypeError, ValueError):
            continue

    lookup_conditions = [OperationsService.skills.in_(keys)]
    if service_ids:
        lookup_conditions.append(OperationsService.id.in_(service_ids))

    stmt = select(OperationsService).where(
        OperationsService.is_deleted.is_(False),
        OperationsService.is_available.is_(True),
        OperationsService.service_type == "compliance",
        or_(*lookup_conditions),
    )
    result = await session.execute(stmt)
    services = result.scalars().all()
    by_id = {str(service.id): service for service in services}
    by_skill = {service.skills: service for service in services if service.skills}

    ordered = []
    seen: set[str] = set()
    for key in keys:
        service = by_id.get(key) or by_skill.get(key)
        if not service:
            continue
        service_id = str(service.id)
        if service_id in seen:
            continue
        seen.add(service_id)
        ordered.append(service)
    return ordered


async def resolve_live_compliance_addon_amount(
    session: AsyncSession,
    addon_services: str | list | None,
) -> float:
    services = await resolve_live_compliance_addon_services(session, addon_services)
    return sum(float(service.price or 0) for service in services)


async def create_addon_operations_requests(
    session: AsyncSession,
    *,
    user_id: Any,
    buyer_name: str,
    buyer_email: str,
    buyer_phone: str,
    addon_services_csv: str | None,
) -> None:
    """Create pending Operations requests for selected compliance addons."""
    if not addon_services_csv:
        return

    from app.entity.operations.operations_service_request_entity import OperationsServiceRequest

    services = await resolve_live_compliance_addon_services(session, addon_services_csv)
    for service in services:
        # Check if pending request already exists
        check_stmt = select(OperationsServiceRequest).where(
            OperationsServiceRequest.user_id == user_id,
            OperationsServiceRequest.operations_service_id == service.id,
            OperationsServiceRequest.status == "PENDING",
        )
        check_result = await session.execute(check_stmt)
        existing = check_result.scalar_one_or_none()
        if existing:
            continue

        # Create a new operations request in PENDING status
        req = OperationsServiceRequest(
            operations_service_id=service.id,
            user_id=user_id,
            request_type="booking",
            service_type=service.service_type,
            billing_period="one_time",
            service_name=service.name,
            quoted_price=float(service.price or 0),
            full_name=buyer_name.strip() or "—",
            email=buyer_email.strip() or "—",
            phone=buyer_phone.strip() or "—",
            message="Created automatically via addon selection during checkout.",
            status="PENDING",
        )
        session.add(req)

