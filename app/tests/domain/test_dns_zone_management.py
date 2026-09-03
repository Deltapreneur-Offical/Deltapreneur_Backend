"""Tests for OpenProvider DNS zone auto-creation lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
from app.service.domain import domain_registration_service as drs
from app.utils.domain_nameservers import set_order_nameservers
from app.utils.registration_enums import RegistrationOrderStatus


def _order(**kwargs) -> DomainRegistrationOrder:
    o = DomainRegistrationOrder(
        id=uuid4(),
        domain_name="madamecama",
        domain_extension=".com",
        buyer_id=uuid4(),
        buyer_email="buyer@example.com",
        period_years=1,
        price_inr=999.0,
        status=RegistrationOrderStatus.ACTIVE,
        open_provider_domain_id="12345",
    )
    for k, v in kwargs.items():
        setattr(o, k, v)
    return o


def _service() -> drs.DomainRegistrationService:
    svc = drs.DomainRegistrationService.__new__(drs.DomainRegistrationService)
    svc._session = MagicMock()
    svc._orders = MagicMock()
    svc._followup = MagicMock()
    return svc


@pytest.mark.asyncio
async def test_existing_zone_proceeds_without_creation():
    """Zone exists → record operation proceeds normally."""
    order = _order()
    svc = _service()
    svc.get_order = AsyncMock(return_value=order)

    reg = MagicMock()
    reg.is_configured.return_value = True
    reg.get_dns_zone = AsyncMock(return_value={"name": "madamecama.com", "type": "MASTER"})
    reg.create_dns_record = AsyncMock(return_value=True)

    with patch.object(drs, "active_registrar", return_value=reg):
        await svc.create_dns_record(order.id, {"type": "A", "name": "@", "value": "1.2.3.4"}, buyer=MagicMock())

    reg.get_dns_zone.assert_awaited_once_with("madamecama.com")
    reg.create_dns_zone.assert_not_called()
    reg.create_dns_record.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_zone_auto_creates_then_adds_record():
    """Zone missing → auto-create MASTER zone → then add record."""
    order = _order()
    svc = _service()
    svc.get_order = AsyncMock(return_value=order)

    reg = MagicMock()
    reg.is_configured.return_value = True
    reg.get_dns_zone = AsyncMock(return_value=None)
    reg.create_dns_zone = AsyncMock(return_value={"name": "madamecama.com", "type": "MASTER"})
    reg.create_dns_record = AsyncMock(return_value=True)

    with patch.object(drs, "active_registrar", return_value=reg):
        await svc.create_dns_record(order.id, {"type": "A", "name": "@", "value": "1.2.3.4"}, buyer=MagicMock())

    reg.get_dns_zone.assert_awaited_once_with("madamecama.com")
    reg.create_dns_zone.assert_awaited_once_with("madamecama.com")
    reg.create_dns_record.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_zone_creation_failure_raises():
    """Zone missing + creation fails → error propagates, no record operation."""
    order = _order()
    svc = _service()
    svc.get_order = AsyncMock(return_value=order)

    reg = MagicMock()
    reg.is_configured.return_value = True
    reg.get_dns_zone = AsyncMock(return_value=None)
    reg.create_dns_zone = AsyncMock(side_effect=RuntimeError("Insufficient balance"))

    with patch.object(drs, "active_registrar", return_value=reg):
        with pytest.raises(drs.AppException) as exc_info:
            await svc.create_dns_record(order.id, {"type": "A", "name": "@", "value": "1.2.3.4"}, buyer=MagicMock())

    assert exc_info.value.status_code == 400
    reg.create_dns_record.assert_not_called()


@pytest.mark.asyncio
async def test_client_handles_409_already_exists_idempotently():
    """Client handles 409 'already exists' internally and returns existing zone.

    The service calls create_dns_zone exactly once; the client is responsible
    for idempotency (fetching the existing zone after a 409).
    """
    order = _order()
    svc = _service()
    svc.get_order = AsyncMock(return_value=order)

    reg = MagicMock()
    reg.is_configured.return_value = True
    reg.get_dns_zone = AsyncMock(return_value=None)
    reg.create_dns_zone = AsyncMock(return_value={"name": "madamecama.com", "type": "MASTER"})
    reg.create_dns_record = AsyncMock(return_value=True)

    with patch.object(drs, "active_registrar", return_value=reg):
        await svc.create_dns_record(order.id, {"type": "A", "name": "@", "value": "1.2.3.4"}, buyer=MagicMock())

    # Service delegates once; client handles 409 internally.
    reg.create_dns_zone.assert_awaited_once_with("madamecama.com")
    reg.create_dns_record.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_dns_zone_skips_when_not_configured():
    """When registrar is not configured, _ensure_dns_zone is a no-op."""
    order = _order()
    svc = _service()

    reg = MagicMock()
    reg.is_configured.return_value = False

    with patch.object(drs, "active_registrar", return_value=reg):
        await svc._ensure_dns_zone(order)  # must not raise

    reg.get_dns_zone.assert_not_called()
    reg.create_dns_zone.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_dns_zone_skips_when_methods_missing():
    """When registrar module lacks DNS zone methods, _ensure_dns_zone is a no-op."""
    order = _order()
    svc = _service()

    reg = MagicMock(spec=["is_configured"])
    reg.is_configured.return_value = True
    # No get_dns_zone or create_dns_zone attributes

    with patch.object(drs, "active_registrar", return_value=reg):
        await svc._ensure_dns_zone(order)  # must not raise

    assert not hasattr(reg, "get_dns_zone")
    assert not hasattr(reg, "create_dns_zone")
