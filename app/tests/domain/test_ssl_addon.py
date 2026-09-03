"""OpenProvider SSL catalog, commission markup, and provision helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.openprovider.client import extract_ssl_period_price
from app.service.domain.domain_registration_service import DomainRegistrationService


def test_extract_ssl_period_price_prefers_reseller():
    product = {
        "id": 5,
        "prices": [
            {
                "period": 1,
                "price": {
                    "product": {"currency": "USD", "price": 50.0},
                    "reseller": {"currency": "EUR", "price": 9.77},
                },
            }
        ],
    }
    amount, currency = extract_ssl_period_price(product, 1)
    assert amount == 9.77
    assert currency == "EUR"


def test_extract_ssl_period_price_missing_raises():
    with pytest.raises(RuntimeError, match="No SSL price"):
        extract_ssl_period_price({"id": 1, "prices": []}, 1)


@pytest.mark.asyncio
async def test_build_live_ssl_price_block_applies_admin_ssl_commission(monkeypatch):
    products = [
        {
            "id": 10,
            "name": "EssentialSSL",
            "brand_name": "Comodo",
            "category": "domain_validation",
            "is_wildcard_supported": False,
            "max_period": 2,
            "prices": [
                {
                    "period": 1,
                    "price": {
                        "reseller": {"currency": "INR", "price": 1000.0},
                    },
                }
            ],
        },
        {
            "id": 11,
            "name": "EssentialSSL Wildcard",
            "brand_name": "Comodo",
            "category": "domain_validation",
            "is_wildcard_supported": True,
            "max_period": 1,
            "prices": [
                {
                    "period": 1,
                    "price": {
                        "reseller": {"currency": "INR", "price": 3000.0},
                    },
                }
            ],
        },
    ]

    async def fake_fetch(self):
        return products

    monkeypatch.setattr(
        DomainRegistrationService,
        "_fetch_ssl_products_priced",
        fake_fetch,
    )
    monkeypatch.setattr(
        "app.service.domain.domain_commission_config.get_rate",
        lambda service, tld=None: 0.10 if service == "ssl" else 0.0,
    )

    svc = DomainRegistrationService(MagicMock())

    def _apply(base: float, service: str, tld: str | None = None) -> dict:
        from app.service.domain import domain_commission_config as commission

        rate = commission.get_rate(service, tld)
        final = commission.apply_markup(base, rate)
        return {"base": round(base, 2), "commissionRate": rate, "final": final}

    block = await svc._build_live_ssl_price_block(_apply)
    assert block["source"] == "openprovider"
    assert block["standard"]["productId"] == 10
    assert block["standard"]["base"] == 1000.0
    assert block["standard"]["commissionRate"] == 0.10
    assert block["standard"]["unitInr"] == 1100.0
    assert block["wildcard"]["unitInr"] == 3300.0
    assert "From ₹1100" in (block["label"] or "")


@pytest.mark.asyncio
async def test_resolve_ssl_product_quote_rejects_unknown(monkeypatch):
    async def fake_fetch(self):
        return []

    monkeypatch.setattr(
        DomainRegistrationService,
        "_fetch_ssl_products_priced",
        fake_fetch,
    )
    svc = DomainRegistrationService(MagicMock())
    with pytest.raises(Exception) as exc:
        await svc._resolve_ssl_product_quote(product_id=999, period=1)
    assert getattr(exc.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_add_ssl_addon_provisions_via_openprovider(monkeypatch):
    from app.core.exceptions import AppException
    from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
    from app.utils.registration_enums import RegistrationOrderStatus
    import uuid

    order = DomainRegistrationOrder(
        domain_name="example",
        domain_extension=".com",
        buyer_id=uuid.uuid4(),
        buyer_full_name="Test User",
        buyer_email="admin@example.com",
        country="IN",
        city="Bengaluru",
        state="KA",
        price_inr=1.0,
        status=RegistrationOrderStatus.ACTIVE,
        open_provider_handle="TH000001-NL",
        open_provider_domain_id="12345",
    )
    order.id = uuid.uuid4()

    session = MagicMock()
    svc = DomainRegistrationService(session)
    buyer = MagicMock()
    buyer.id = order.buyer_id

    async def fake_get_order(order_id, *, buyer):
        return order

    async def fake_csr(**kwargs):
        return {"csr": "-----BEGIN CERTIFICATE REQUEST-----\nCSR\n-----END CERTIFICATE REQUEST-----",
                "key": "-----BEGIN PRIVATE KEY-----\nKEY\n-----END PRIVATE KEY-----"}

    async def fake_create(payload):
        assert payload["product_id"] == 10
        assert payload["start_provision"] is True
        assert payload["approver_email"] == "admin@example.com"
        return 555

    async def fake_sync(o):
        return None

    async def fake_detail(order_id, *, buyer, sync=False):
        return {"id": str(order_id), "dnsRecords": order.dns_records_json}

    monkeypatch.setattr(svc, "get_order", fake_get_order)
    monkeypatch.setattr(svc, "get_order_detail", fake_detail)
    monkeypatch.setattr(svc._orders, "save", AsyncMock())
    monkeypatch.setattr(svc._session, "commit", AsyncMock())
    monkeypatch.setattr(svc._followup, "sync_ssl_addon", fake_sync)
    monkeypatch.setattr(
        "app.integrations.openprovider.client.generate_ssl_csr",
        fake_csr,
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.create_ssl_order",
        fake_create,
    )
    monkeypatch.setattr(
        "app.service.domain.domain_registration_followup.dnssec_management_supported",
        lambda o: False,
    )

    result = await svc.add_ssl_addon(
        order.id,
        buyer=buyer,
        _payment_verified=True,
        pending_payload={
            "productId": 10,
            "productName": "EssentialSSL",
            "period": 1,
            "approverEmail": "admin@example.com",
            "validationMethod": "email",
            "hostNames": ["www.example.com"],
            "wildcard": False,
            "unitInr": 1100.0,
            "commissionRate": 0.1,
        },
    )
    assert result["id"] == str(order.id)
    import json
    addons = json.loads(order.dns_records_json)
    assert addons["ssl"]["opOrderId"] == 555
    assert addons["ssl"]["privateKey"].startswith("-----BEGIN PRIVATE KEY-----")
    assert addons["ssl"]["status"] == "REQ"

    with pytest.raises(AppException) as unpaid:
        await svc.add_ssl_addon(order.id, buyer=buyer, _payment_verified=False)
    assert unpaid.value.status_code == 402
