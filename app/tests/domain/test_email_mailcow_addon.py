"""Mailcow email addon provision (mocked OpenProvider)."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AppException
from app.service.domain.domain_registration_service import DomainRegistrationService


def _order(*, handle: str = "XX123456-XX") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        domain_name="example",
        domain_extension=".com",
        fqdn="example.com",
        open_provider_handle=handle,
        buyer_full_name="Test Buyer",
        dns_records_json=json.dumps({}),
    )


@pytest.mark.asyncio
async def test_add_email_addon_requires_payment():
    svc = DomainRegistrationService(MagicMock())
    with pytest.raises(AppException) as exc:
        await svc.add_email_addon(uuid.uuid4(), "info", buyer=MagicMock(), _payment_verified=False)
    assert exc.value.status_code == 402


@pytest.mark.asyncio
async def test_add_email_addon_provisions_mailcow(monkeypatch):
    order = _order()
    buyer = MagicMock()

    svc = DomainRegistrationService(MagicMock())
    svc.get_order = AsyncMock(return_value=order)
    svc._orders = MagicMock()
    svc._orders.save = AsyncMock()
    svc._session = MagicMock()
    svc._session.commit = AsyncMock()
    svc.get_order_detail = AsyncMock(return_value={"id": str(order.id), "domain": "example.com"})

    mailcow_list_domains = AsyncMock(return_value=[])
    mailcow_add_domain = AsyncMock(return_value={"status": "ok"})
    mailcow_create_order = AsyncMock(return_value={"success": True})
    mailcow_assign_mailbox = AsyncMock(
        return_value={"id": 42, "status": "active", "mailbox_status": "active"}
    )
    mailcow_increase_mailbox_quota = AsyncMock(return_value=True)
    mailcow_get_mailbox_password = AsyncMock(return_value="unused")

    monkeypatch.setattr(
        "app.integrations.openprovider.client.mailcow_list_domains",
        mailcow_list_domains,
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.mailcow_add_domain",
        mailcow_add_domain,
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.mailcow_create_order",
        mailcow_create_order,
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.mailcow_assign_mailbox",
        mailcow_assign_mailbox,
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.mailcow_increase_mailbox_quota",
        mailcow_increase_mailbox_quota,
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.mailcow_get_mailbox_password",
        mailcow_get_mailbox_password,
    )

    result = await svc.add_email_addon(
        order.id,
        "info",
        buyer=buyer,
        _payment_verified=True,
        pending_payload={"mailbox": "info", "months": 1, "quotaGb": 5},
    )

    mailcow_add_domain.assert_awaited_once()
    mailcow_create_order.assert_awaited_once()
    mailcow_assign_mailbox.assert_awaited_once()
    mailcow_increase_mailbox_quota.assert_awaited_once()
    assert result["mailboxProvisioned"]["address"] == "info@example.com"
    assert result["mailboxProvisioned"]["opOrderId"] == 42
    assert result["mailboxProvisioned"]["password"]

    saved = json.loads(order.dns_records_json)
    assert isinstance(saved["mailboxes"], list)
    assert saved["mailboxes"][0]["address"] == "info@example.com"
    assert "mailbox_passwords" not in saved


def _svc(order):
    svc = DomainRegistrationService(MagicMock())
    svc.get_order = AsyncMock(return_value=order)
    svc._orders = MagicMock()
    svc._orders.save = AsyncMock()
    svc._session = MagicMock()
    svc._session.commit = AsyncMock()
    svc.get_order_detail = AsyncMock(return_value={"id": str(order.id), "domain": order.fqdn})
    return svc


@pytest.mark.asyncio
async def test_email_idempotent_skips_reprovision(monkeypatch):
    order = _order()
    order.dns_records_json = json.dumps(
        {
            "mailboxes": [
                {
                    "address": "info@example.com",
                    "localPart": "info",
                    "opOrderId": 42,
                    "status": "active",
                    "quotaGb": 5,
                    "months": 1,
                }
            ]
        }
    )
    svc = _svc(order)
    list_domains = AsyncMock()
    monkeypatch.setattr(
        "app.integrations.openprovider.client.mailcow_list_domains",
        list_domains,
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.mailcow_get_mailbox_password",
        AsyncMock(return_value="recovered"),
    )
    result = await svc.add_email_addon(
        order.id,
        "info",
        buyer=MagicMock(),
        _payment_verified=True,
        pending_payload={"mailbox": "info", "months": 1, "quotaGb": 5},
    )
    list_domains.assert_not_called()
    assert result["mailboxProvisioned"]["alreadyProvisioned"] is True
    assert result["mailboxProvisioned"]["password"] == "recovered"


@pytest.mark.asyncio
async def test_verify_email_keeps_pending_on_op_failure(monkeypatch):
    order = _order()
    order.dns_records_json = json.dumps(
        {
            "_pendingAddon": {
                "type": "email",
                "razorpayOrderId": "order_abc",
                "payload": {"mailbox": "info", "months": 1, "quotaGb": 5},
                "paymentVerified": False,
            }
        }
    )
    svc = _svc(order)
    monkeypatch.setattr(
        "app.service.domain.domain_registration_service.rzp.verify_payment_signature",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.mailcow_list_domains",
        AsyncMock(side_effect=RuntimeError("OP down")),
    )
    with pytest.raises(AppException):
        await svc.verify_email_addon_payment(
            order.id,
            {
                "razorpayOrderId": "order_abc",
                "razorpayPaymentId": "pay_1",
                "razorpaySignature": "sig",
            },
            buyer=MagicMock(),
        )
    saved = json.loads(order.dns_records_json)
    assert saved["_pendingAddon"]["paymentVerified"] is True
    assert saved["_pendingAddon"]["type"] == "email"


@pytest.mark.asyncio
async def test_verify_email_success_clears_pending(monkeypatch):
    order = _order()
    order.dns_records_json = json.dumps(
        {
            "_pendingAddon": {
                "type": "email",
                "razorpayOrderId": "order_abc",
                "payload": {"mailbox": "info", "months": 1, "quotaGb": 5},
                "paymentVerified": False,
            }
        }
    )
    svc = _svc(order)
    monkeypatch.setattr(
        "app.service.domain.domain_registration_service.rzp.verify_payment_signature",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.mailcow_list_domains",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.mailcow_add_domain",
        AsyncMock(return_value={"status": "ok"}),
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.mailcow_create_order",
        AsyncMock(return_value={"success": True}),
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.mailcow_assign_mailbox",
        AsyncMock(return_value={"id": 42, "status": "active", "mailbox_status": "active"}),
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.mailcow_increase_mailbox_quota",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.mailcow_get_mailbox_password",
        AsyncMock(return_value="unused"),
    )
    detail = await svc.verify_email_addon_payment(
        order.id,
        {
            "razorpayOrderId": "order_abc",
            "razorpayPaymentId": "pay_1",
            "razorpaySignature": "sig",
        },
        buyer=MagicMock(),
    )
    assert detail["mailboxProvisioned"]["address"] == "info@example.com"
    saved = json.loads(order.dns_records_json)
    assert "_pendingAddon" not in saved
