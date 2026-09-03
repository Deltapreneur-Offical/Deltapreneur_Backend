"""Restore / EasyDMARC / SpamExperts addon provision (mocked OpenProvider)."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AppException
from app.service.domain.domain_registration_service import DomainRegistrationService


def _order(**kwargs) -> SimpleNamespace:
    base = dict(
        id=uuid.uuid4(),
        domain_name="example",
        domain_extension=".com",
        fqdn="example.com",
        open_provider_handle="XX123456-XX",
        open_provider_domain_id="998877",
        buyer_full_name="Test Buyer",
        dns_records_json=json.dumps({}),
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


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
async def test_add_restore_requires_payment():
    svc = DomainRegistrationService(MagicMock())
    with pytest.raises(AppException) as exc:
        await svc.add_restore_addon(uuid.uuid4(), buyer=MagicMock(), _payment_verified=False)
    assert exc.value.status_code == 402


@pytest.mark.asyncio
async def test_add_restore_calls_openprovider(monkeypatch):
    order = _order()
    svc = _svc(order)
    restore_domain = AsyncMock(return_value={"status": "ACT"})
    monkeypatch.setattr(
        "app.integrations.openprovider.client.restore_domain",
        restore_domain,
    )
    result = await svc.add_restore_addon(order.id, buyer=MagicMock(), _payment_verified=True)
    restore_domain.assert_awaited_once()
    assert result["restoreProvisioned"]["status"] == "ACT"
    saved = json.loads(order.dns_records_json)
    assert saved["restore"]["opDomainId"] == "998877"


@pytest.mark.asyncio
async def test_add_easydmarc_calls_openprovider(monkeypatch):
    order = _order()
    svc = _svc(order)
    easydmarc_create = AsyncMock(
        return_value={
            "id": 55,
            "status": "active",
            "record_host": "_dmarc",
            "record_type": "TXT",
            "record_value": "v=DMARC1",
        }
    )
    easydmarc_sso_url = AsyncMock(return_value="https://example.com/sso")
    monkeypatch.setattr(
        "app.integrations.openprovider.client.easydmarc_create",
        easydmarc_create,
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.easydmarc_sso_url",
        easydmarc_sso_url,
    )
    result = await svc.add_easydmarc_addon(order.id, buyer=MagicMock(), _payment_verified=True)
    easydmarc_create.assert_awaited_once()
    assert result["easydmarcProvisioned"]["opOrderId"] == 55
    assert result["easydmarcProvisioned"]["ssoUrl"] == "https://example.com/sso"


@pytest.mark.asyncio
async def test_add_spamexperts_calls_openprovider(monkeypatch):
    order = _order()
    svc = _svc(order)
    create = AsyncMock(return_value={"ok": True})
    login = AsyncMock(return_value="https://spam.example/login")
    monkeypatch.setattr(
        "app.integrations.openprovider.client.spam_expert_create_domain",
        create,
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.spam_expert_generate_login_url",
        login,
    )
    result = await svc.add_spamexperts_addon(
        order.id,
        buyer=MagicMock(),
        _payment_verified=True,
        pending_payload={"destinationHost": "mx.example.com"},
    )
    create.assert_awaited_once()
    login.assert_awaited_once()
    assert result["spamexpertsProvisioned"]["loginUrl"] == "https://spam.example/login"
    assert result["spamexpertsProvisioned"]["destinationHost"] == "mx.example.com"
    assert result["spamexpertsProvisioned"]["mxRecords"][0]["host"] == "mx.spamexperts.com"
    assert result["spamexpertsProvisioned"]["mxRecords"][0]["priority"] == 100


@pytest.mark.asyncio
async def test_easydmarc_fills_dns_from_get_when_create_omits(monkeypatch):
    order = _order()
    svc = _svc(order)
    easydmarc_create = AsyncMock(return_value={"id": 77, "status": "active"})
    easydmarc_get = AsyncMock(
        return_value={
            "record_host": "_dmarc",
            "record_type": "TXT",
            "record_value": "v=DMARC1; p=none",
        }
    )
    easydmarc_sso_url = AsyncMock(return_value="https://example.com/sso")
    monkeypatch.setattr(
        "app.integrations.openprovider.client.easydmarc_create",
        easydmarc_create,
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.easydmarc_get",
        easydmarc_get,
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.easydmarc_sso_url",
        easydmarc_sso_url,
    )
    result = await svc.add_easydmarc_addon(order.id, buyer=MagicMock(), _payment_verified=True)
    easydmarc_get.assert_awaited_once_with(77)
    assert result["easydmarcProvisioned"]["recordHost"] == "_dmarc"
    assert result["easydmarcProvisioned"]["recordValue"] == "v=DMARC1; p=none"


@pytest.mark.asyncio
async def test_easydmarc_idempotent_skips_recreate(monkeypatch):
    order = _order(
        dns_records_json=json.dumps(
            {
                "easydmarc": {
                    "opOrderId": 55,
                    "recordHost": "_dmarc",
                    "recordType": "TXT",
                    "recordValue": "v=DMARC1",
                    "ssoUrl": "https://example.com/sso",
                }
            }
        )
    )
    svc = _svc(order)
    create = AsyncMock()
    monkeypatch.setattr(
        "app.integrations.openprovider.client.easydmarc_create",
        create,
    )
    result = await svc.add_easydmarc_addon(order.id, buyer=MagicMock(), _payment_verified=True)
    create.assert_not_called()
    assert result["easydmarcProvisioned"]["opOrderId"] == 55


@pytest.mark.asyncio
async def test_spamexperts_idempotent_skips_recreate(monkeypatch):
    order = _order(
        dns_records_json=json.dumps(
            {
                "spamexperts": {
                    "status": "active",
                    "destinationHost": "mail.example.com",
                    "loginUrl": "https://spam.example/login",
                }
            }
        )
    )
    svc = _svc(order)
    create = AsyncMock()
    monkeypatch.setattr(
        "app.integrations.openprovider.client.spam_expert_create_domain",
        create,
    )
    result = await svc.add_spamexperts_addon(order.id, buyer=MagicMock(), _payment_verified=True)
    create.assert_not_called()
    assert result["spamexpertsProvisioned"]["mxRecords"][0]["host"] == "mx.spamexperts.com"


@pytest.mark.asyncio
async def test_restore_idempotent_skips_recreate(monkeypatch):
    order = _order(
        dns_records_json=json.dumps(
            {"restore": {"status": "ACT", "opDomainId": "998877"}}
        )
    )
    svc = _svc(order)
    restore_domain = AsyncMock()
    monkeypatch.setattr(
        "app.integrations.openprovider.client.restore_domain",
        restore_domain,
    )
    result = await svc.add_restore_addon(order.id, buyer=MagicMock(), _payment_verified=True)
    restore_domain.assert_not_called()
    assert result["restoreProvisioned"]["status"] == "ACT"


@pytest.mark.asyncio
async def test_verify_easydmarc_success_clears_pending(monkeypatch):
    order = _order(
        dns_records_json=json.dumps(
            {
                "_pendingAddon": {
                    "type": "easydmarc",
                    "razorpayOrderId": "order_abc",
                    "payload": {},
                    "paymentVerified": False,
                }
            }
        )
    )
    svc = _svc(order)
    monkeypatch.setattr(
        "app.service.domain.domain_registration_service.rzp.verify_payment_signature",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.easydmarc_create",
        AsyncMock(
            return_value={
                "id": 9,
                "status": "active",
                "record_host": "_dmarc",
                "record_type": "TXT",
                "record_value": "v=DMARC1",
            }
        ),
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.easydmarc_sso_url",
        AsyncMock(return_value="https://sso.example"),
    )
    detail = await svc.verify_easydmarc_addon_payment(
        order.id,
        {
            "razorpayOrderId": "order_abc",
            "razorpayPaymentId": "pay_1",
            "razorpaySignature": "sig",
        },
        buyer=MagicMock(),
    )
    assert detail["easydmarcProvisioned"]["opOrderId"] == 9
    saved = json.loads(order.dns_records_json)
    assert "_pendingAddon" not in saved
    assert "easydmarc" in saved


@pytest.mark.asyncio
async def test_verify_spamexperts_keeps_pending_on_op_failure(monkeypatch):
    order = _order(
        dns_records_json=json.dumps(
            {
                "_pendingAddon": {
                    "type": "spamexperts",
                    "razorpayOrderId": "order_abc",
                    "payload": {"destinationHost": "mail.example.com"},
                    "paymentVerified": False,
                }
            }
        )
    )
    svc = _svc(order)
    monkeypatch.setattr(
        "app.service.domain.domain_registration_service.rzp.verify_payment_signature",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.spam_expert_create_domain",
        AsyncMock(side_effect=RuntimeError("OP down")),
    )
    with pytest.raises(AppException):
        await svc.verify_spamexperts_addon_payment(
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
    assert saved["_pendingAddon"]["type"] == "spamexperts"


@pytest.mark.asyncio
async def test_verify_easydmarc_keeps_pending_on_op_failure(monkeypatch):
    order = _order(
        dns_records_json=json.dumps(
            {
                "_pendingAddon": {
                    "type": "easydmarc",
                    "razorpayOrderId": "order_abc",
                    "payload": {},
                    "paymentVerified": False,
                }
            }
        )
    )
    svc = _svc(order)
    monkeypatch.setattr(
        "app.service.domain.domain_registration_service.rzp.verify_payment_signature",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.easydmarc_create",
        AsyncMock(side_effect=RuntimeError("OP down")),
    )
    with pytest.raises(AppException):
        await svc.verify_easydmarc_addon_payment(
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


@pytest.mark.asyncio
async def test_verify_restore_retry_after_paid_pending_succeeds(monkeypatch):
    order = _order(
        dns_records_json=json.dumps(
            {
                "_pendingAddon": {
                    "type": "restore",
                    "razorpayOrderId": "order_abc",
                    "razorpayPaymentId": "pay_abc",
                    "paymentVerified": True,
                    "provisionStatus": "paid_pending_provision",
                    "payload": {},
                }
            }
        )
    )
    svc = _svc(order)
    verify = MagicMock(return_value=True)
    monkeypatch.setattr(
        "app.service.domain.domain_registration_service.rzp.verify_payment_signature",
        verify,
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.restore_domain",
        AsyncMock(return_value={"status": "ACT"}),
    )
    detail = await svc.verify_restore_addon_payment(
        order.id,
        {
            "razorpayOrderId": "order_abc",
            "razorpayPaymentId": "pay_abc",
            "razorpaySignature": "sig",
        },
        buyer=MagicMock(),
    )
    verify.assert_not_called()
    assert detail["restoreProvisioned"]["status"] == "ACT"
    saved = json.loads(order.dns_records_json)
    assert "_pendingAddon" not in saved



@pytest.mark.asyncio
async def test_commission_keys_include_new_addons():
    from app.service.domain.domain_commission_config import CommissionService, get_rate

    for key in (
        CommissionService.RESTORE,
        CommissionService.EASYDMARC,
        CommissionService.SPAMEXPERTS,
    ):
        assert key in CommissionService.ALL
        assert isinstance(get_rate(key), float)


@pytest.mark.asyncio
async def test_set_pending_blocks_when_paid_not_provisioned():
    order = _order(
        dns_records_json=json.dumps(
            {
                "_pendingAddon": {
                    "type": "email",
                    "razorpayOrderId": "order_old",
                    "paymentVerified": True,
                    "provisionStatus": "paid_pending_provision",
                }
            }
        )
    )
    svc = _svc(order)
    with pytest.raises(AppException) as exc:
        await svc._set_pending_addon_payment(
            order,
            addon_type="restore",
            razorpay_order_id="order_new",
            amount_inr=100,
            payload={},
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_consume_verified_pending_allows_retry_without_resignature(monkeypatch):
    order = _order(
        dns_records_json=json.dumps(
            {
                "_pendingAddon": {
                    "type": "restore",
                    "razorpayOrderId": "order_abc",
                    "razorpayPaymentId": "pay_abc",
                    "paymentVerified": True,
                    "provisionStatus": "paid_pending_provision",
                    "payload": {},
                }
            }
        )
    )
    svc = _svc(order)
    verify = MagicMock(return_value=True)
    monkeypatch.setattr(
        "app.service.domain.domain_registration_service.rzp.verify_payment_signature",
        verify,
    )
    pending = await svc._consume_verified_pending_addon(
        order,
        {
            "razorpayOrderId": "order_abc",
            "razorpayPaymentId": "pay_abc",
            "razorpaySignature": "sig",
        },
        expected_type="restore",
    )
    assert pending["paymentVerified"] is True
    verify.assert_not_called()


@pytest.mark.asyncio
async def test_verify_restore_keeps_pending_on_op_failure(monkeypatch):
    order = _order(
        dns_records_json=json.dumps(
            {
                "_pendingAddon": {
                    "type": "restore",
                    "razorpayOrderId": "order_abc",
                    "payload": {},
                    "paymentVerified": False,
                }
            }
        )
    )
    svc = _svc(order)
    monkeypatch.setattr(
        "app.service.domain.domain_registration_service.rzp.verify_payment_signature",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.restore_domain",
        AsyncMock(side_effect=RuntimeError("OP down")),
    )
    with pytest.raises(AppException):
        await svc.verify_restore_addon_payment(
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
    assert saved["_pendingAddon"]["type"] == "restore"
    svc._session.commit.assert_awaited()
