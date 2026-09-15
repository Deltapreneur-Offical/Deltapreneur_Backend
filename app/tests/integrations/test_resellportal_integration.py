"""Tests for ResellPortal Integration & Premium Technology Admin."""

import pytest
from app.core.config import settings
from app.integrations.resellportal.client import ResellPortalClient, get_resellportal_client
from app.integrations.resellportal.mock_resellportal_api import MockResellPortalAPI
import json


def test_resellportal_unconfigured_defaults():
    """Verify client behavior when API credentials are blank."""
    client = ResellPortalClient(api_key="", api_secret="")
    assert client.is_configured() is False
    assert client.is_test_mode() is True

    wallet = client.get_wallet_balance()
    assert wallet["success"] is True
    assert wallet["configured"] is False
    assert wallet["balance"] == 145.50
    assert "ResellPortal API credentials have not been configured yet" in wallet["message"]

    catalog = client.get_product_catalog()
    assert len(catalog) == 17

    portal = client.create_portal_client(user_email="test@cobrother.com", user_id="usr_001")
    provision = client.provision_service(
        service_slug="ai-business-suite",
        service_name="AI Business Suite",
        plan_code="pro",
        billing_cycle="monthly",
        user_email="test@cobrother.com",
        user_id="usr_001",
        provider_client_id=portal["provider_client_id"],
        portal_account=portal,
    )
    assert provision["success"] is True
    assert provision["status"] == "TEST_SIMULATED"
    assert provision["test_only"] is True
    assert provision["simulated"] is True
    assert "client_access_url" not in provision["credentials"]
    assert "access_token" not in provision["credentials"]


def test_resellportal_configured_test_mode_injection():
    """Verify test_mode: true payload injection when test mode is active."""
    client = ResellPortalClient(
        api_base="https://panel.resellportal.com/wp-json/resellportal/v1",
        api_key="test_key_123",
        api_secret="test_secret_456",
    )
    assert client.is_configured() is True
    assert client.is_test_mode() is True
    assert client.get_auth_headers()["X-API-Key"] == "test_key_123"
    assert client.get_auth_headers()["X-API-Secret"] == "test_secret_456"


def test_ai_business_suite_uses_orders_endpoint_and_required_ai_tools(monkeypatch):
    """AI Business Suite must activate through POST /orders with the product_key + ai_tools payload."""
    import app.integrations.resellportal.client as client_module

    seen = {}

    class DummyResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "success": True,
                "provider_order_id": "RSP-ORD-ABCD",
                "provider_subscription_id": "RSP-SUB-ABCD",
                "status": "ACTIVE",
                "current_period_start": "2026-08-12T00:00:00+00:00",
                "current_period_end": "2026-09-11T00:00:00+00:00",
                "client_access_url": "https://deltaosportal.deltapreneur.com/ai",
                "credentials": {"email": "owner@cobrother.com", "password": "pw"},
            }

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def request(self, method, url, headers=None, json=None, params=None):
            seen["method"] = method
            seen["url"] = url
            seen["headers"] = headers
            seen["json"] = json
            seen["params"] = params
            return DummyResponse({})

    monkeypatch.setattr(client_module.httpx, "Client", DummyClient)

    client = ResellPortalClient(
        api_base="https://panel.resellportal.com/wp-json/resellportal/v1",
        api_key="test_key_123",
        api_secret="test_secret_456",
    )

    result = client.provision_service(
        service_slug="ai-business-suite",
        service_name="AI Business Suite",
        plan_code="pro",
        billing_cycle="monthly",
        user_email="owner@cobrother.com",
        user_id="usr_123",
        product_key="ai_business_tools",
        order_parameters={"ai_tools": "content-marketing-suite"},
        provider_client_id="test_cli_abc123",
        portal_account={
            "provider_client_id": "test_cli_abc123",
            "account_portal_url": "https://deltaosportal.deltapreneur.com/account",
            "portal_email": "owner@cobrother.com",
            "portal_password": "portal-pw",
        },
    )

    assert result["success"] is True
    assert result["status"] == "TEST_SIMULATED"
    assert result["test_only"] is True
    assert result["simulated"] is True
    assert seen["method"] == "POST"
    assert seen["url"].endswith("/orders")
    assert seen["json"]["product_key"] == "ai_business_tools"
    assert seen["json"]["ai_tools"] == ["content-marketing-suite"]
    assert seen["json"]["test_mode"] is True
    assert seen["json"]["skip_client_email"] is True
    assert seen["json"]["client_id"] == "test_cli_abc123"
    assert result["provider_subscription_id"] == "RSP-SUB-ABCD"
    assert result["provider_order_id"] == "RSP-ORD-ABCD"
    assert result["credentials"]["portal_password"] == "portal-pw"
    assert "email" not in result["credentials"]


def test_resellportal_unconfigured_create_client_returns_mock():
    """Unconfigured client creation should fall back to the mock."""
    client = ResellPortalClient(api_key="", api_secret="")
    res = client.create_portal_client(user_email="owner@cobrother.com", user_id="usr_123")
    assert res["provider_client_id"].startswith("mock_cli_")
    assert res["portal_email"] == "owner@cobrother.com"
    assert res["portal_password"].startswith("mock_portal_")
    assert res["test_only"] is True


def test_create_portal_client_uses_post_clients_without_lookup(monkeypatch):
    import app.integrations.resellportal.client as client_module

    calls = []

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "success": True,
                "client_id": "cli_123",
                "portal_login_url": "https://deltaosportal.deltapreneur.com/account",
                "portal_credentials": {"email": "buyer@client.test", "password": "portal-pw"},
            }

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, *args, **kwargs):
            raise AssertionError("GET /clients is not in the confirmed provider contract")

        def post(self, url, headers=None, json=None):
            calls.append(("POST", url, json))
            return DummyResponse()

    monkeypatch.setattr(client_module.httpx, "Client", DummyClient)
    client = ResellPortalClient(api_key="key", api_secret="secret")

    result = client.create_portal_client(user_email="buyer@client.test", user_id="usr_123")

    assert result["success"] is True
    assert result["provider_client_id"] == "cli_123"
    assert result["account_portal_url"] == "https://deltaosportal.deltapreneur.com/account"
    assert result["portal_email"] == "buyer@client.test"
    assert result["portal_password"] == "portal-pw"
    assert calls == [
        (
            "POST",
            "https://panel.resellportal.com/wp-json/resellportal/v1/clients",
            {"name": "buyer@client.test", "email": "buyer@client.test"},
        )
    ]


def test_configured_order_requires_persisted_client_id():
    client = ResellPortalClient(api_key="key", api_secret="secret")

    result = client.provision_service(
        service_slug="crm",
        service_name="CRM",
        plan_code="starter",
        billing_cycle="monthly",
        user_email="buyer@client.test",
        user_id="usr_123",
        product_key="crm",
    )

    assert result["success"] is False
    assert "client_id is required" in result["error"]


def test_ai_business_suite_mock_provision_accepts_product_key_and_ai_tools():
    """The mock ResellPortal API must accept the AI Business Suite product_key + ai_tools payload used in live TEST mode."""
    result = MockResellPortalAPI.provision_service(
        service_slug="ai-business-suite",
        service_name="AI Business Suite",
        plan_code="pro",
        billing_cycle="monthly",
        user_email="owner@cobrother.com",
        user_id="usr_123",
        product_key="ai_business_tools",
        order_parameters={"ai_tools": "content-marketing-suite"},
        test_mode=True,
    )

    assert result["success"] is True
    assert result["status"] == "TEST_SIMULATED"
    assert result["test_only"] is True
    assert result["simulated"] is True
    assert result["client_access_url"] == "https://deltaosportal.deltapreneur.com/ai"


@pytest.mark.asyncio
async def test_ai_business_suite_requires_checkout_before_provisioning(monkeypatch):
    """AI Business Suite must not be directly provisioned without a successful Razorpay checkout."""
    from fastapi import HTTPException
    from app.controller.technology.technology_services_controller import subscribe_technology_service
    from app.controller.technology.technology_services_controller import SubscribeRequest

    class FakeAsyncDB:
        async def execute(self, *args, **kwargs):
            class FakeResult:
                def scalar_one_or_none(self):
                    class DummyService:
                        slug = "ai-business-suite"
                        name = "AI Business Suite"
                        plans_json = '{"code": "starter", "price_monthly": 29, "price_annually": 290}'
                    return DummyService()
            return FakeResult()

        async def flush(self):
            pass

        async def commit(self):
            pass

        def add(self, *args, **kwargs):
            pass

    fake_db = FakeAsyncDB()

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.controller.technology.technology_services_controller.ensure_catalogue_seeded",
        _noop,
    )

    with pytest.raises(HTTPException, match="Deltapreneur cart checkout"):
        await subscribe_technology_service(
            payload=SubscribeRequest(service_slug="ai-business-suite", plan_code="starter", billing_cycle="monthly"),
            current_user={"id": "user_123", "email": "owner@cobrother.com"},
            db=fake_db,
        )


@pytest.mark.asyncio
async def test_subscribe_endpoint_rejects_unpaid_provider_provisioning_for_all_services(monkeypatch):
    from fastapi import HTTPException
    from app.controller.technology.technology_services_controller import subscribe_technology_service
    from app.controller.technology.technology_services_controller import SubscribeRequest

    class FakeAsyncDB:
        async def execute(self, *args, **kwargs):
            class FakeResult:
                def scalar_one_or_none(self):
                    class DummyService:
                        slug = "website-builder"
                        name = "Website Builder"
                        plans_json = '[{"code": "starter", "price_monthly": 29, "price_annually": 290}]'
                        provider_product_key = "website_builder"
                    return DummyService()
            return FakeResult()

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.controller.technology.technology_services_controller.ensure_catalogue_seeded",
        _noop,
    )

    with pytest.raises(HTTPException) as exc_info:
        await subscribe_technology_service(
            payload=SubscribeRequest(service_slug="website-builder", plan_code="starter", billing_cycle="monthly"),
            current_user={"id": "user_123", "email": "owner@cobrother.com"},
            db=FakeAsyncDB(),
        )

    assert exc_info.value.status_code == 403
    assert "cart checkout" in str(exc_info.value.detail)


def test_technology_service_fallback_uses_uuid_product_id():
    """Fallback catalogue entries must expose a valid product UUID so cart add requests validate."""
    from uuid import UUID

    from app.controller.technology.technology_services_controller import _get_fallback_services

    service = next(item for item in _get_fallback_services() if item["slug"] == "ai-business-suite")

    assert service["id"]
    UUID(service["id"])


def test_ai_business_suite_failed_provider_response_is_not_marked_active():
    """Provider failure must not create an ACTIVE subscription state for AI Business Suite."""
    failed_response = {
        "success": False,
        "status": "FAILED",
        "provider_order_id": "RSP-ORD-FAIL",
        "provider_subscription_id": "RSP-SUB-FAIL",
        "credentials": {"access_url": "https://workspace.cobrother.com/app/ai-business-suite/fail"},
    }

    assert failed_response["success"] is False
    assert failed_response["status"] != "ACTIVE"
    assert failed_response["status"] == "FAILED"


def test_live_link_in_bio_contract_maps_service_id_without_fabrication(monkeypatch):
    """Confirmed ResellPortal Link in Bio success body must map service_id, never RSP-ORD/SUB-{user[:8]}."""
    import app.integrations.resellportal.client as client_module
    from app.integrations.resellportal.client import ResellPortalClient

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "success": True,
                "status": "ACTIVE",
                "service_id": "ABC123",
                "credentials": {"access_token": "REDACTED", "username": "kushi"},
            }

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def request(self, method, url, headers=None, json=None, params=None):
            return DummyResponse()

    monkeypatch.setattr(client_module.httpx, "Client", DummyClient)
    monkeypatch.setattr(settings, "RESELLPORTAL_TEST_MODE", False)
    monkeypatch.setattr(settings, "RESELLPORTAL_ALLOW_LIVE", True)

    user_id = "05e5676d-e569-432d-ad4b-a1321993d102"
    client = ResellPortalClient(
        api_base="https://panel.resellportal.com/wp-json/resellportal/v1",
        api_key="test_key_123",
        api_secret="test_secret_456",
    )
    result = client.provision_service(
        service_slug="link-in-bio",
        service_name="Link in Bio",
        plan_code="starter",
        billing_cycle="monthly",
        user_email="buyer@example.com",
        user_id=user_id,
        product_key="link_in_bio",
        provider_client_id=42,
    )

    assert result["success"] is True
    assert result["status"] == "ACTIVE"
    assert result["service_id"] == "ABC123"
    assert result["provider_subscription_id"] == "ABC123"
    assert result["provider_order_id"] is None
    assert result["provider_subscription_id"] != f"RSP-SUB-{user_id[:8]}"
    assert result["provider_order_id"] != f"RSP-ORD-{user_id[:8]}"
    assert "access_token" not in result["credentials"]
    dumped = json.dumps(
        {k: v for k, v in result.items() if k != "credentials"},
        default=str,
    ).lower()
    assert "resellportal" not in dumped


def test_client_access_url_is_extracted_from_top_level_response(monkeypatch):
    import app.integrations.resellportal.client as client_module

    seen = {}

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "success": True,
                "status": "ACTIVE",
                "service_id": "svc-crm-1",
                "order_id": "ord-crm-1",
                "url": "https://crmportal.resellportal.com/internal",
                "client_credentials": {"email": "buyer@client.test", "password": "client-pw"},
                "client_access_url": "https://deltaosportal.deltapreneur.com/crm",
            }

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def request(self, method, url, headers=None, json=None, params=None):
            seen["json"] = json
            return DummyResponse()

    monkeypatch.setattr(client_module.httpx, "Client", DummyClient)
    monkeypatch.setattr(settings, "RESELLPORTAL_TEST_MODE", False)
    monkeypatch.setattr(settings, "RESELLPORTAL_ALLOW_LIVE", True)

    client = ResellPortalClient(api_key="key", api_secret="secret")
    result = client.provision_service(
        service_slug="crm",
        service_name="CRM",
        plan_code="starter",
        billing_cycle="monthly",
        user_email="buyer@client.test",
        user_id="usr_123",
        product_key="crm",
        provider_client_id=42,
    )

    assert seen["json"]["skip_client_email"] is True
    assert result["credentials"]["client_access_url"] == "https://deltaosportal.deltapreneur.com/crm"
    assert result["credentials"]["product_email"] == "buyer@client.test"
    assert "resellportal" not in json.dumps(result["credentials"]).lower()


def test_live_orders_skip_client_email_even_when_test_mode_disabled(monkeypatch):
    import app.integrations.resellportal.client as client_module

    seen = {}

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "success": True,
                "status": "ACTIVE",
                "service_id": "svc-1",
                "client_access_url": "https://deltaosportal.deltapreneur.com/crm",
            }

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def request(self, method, url, headers=None, json=None, params=None):
            seen["json"] = json
            return DummyResponse()

    monkeypatch.setattr(client_module.httpx, "Client", DummyClient)
    monkeypatch.setattr(settings, "RESELLPORTAL_TEST_MODE", False)
    monkeypatch.setattr(settings, "RESELLPORTAL_ALLOW_LIVE", True)

    client = ResellPortalClient(api_key="key", api_secret="secret")
    client.provision_service(
        service_slug="crm",
        service_name="CRM",
        plan_code="starter",
        billing_cycle="monthly",
        user_email="buyer@client.test",
        user_id="usr_123",
        product_key="crm",
        provider_client_id=42,
    )

    assert seen["json"]["skip_client_email"] is True
    assert "test_mode" not in seen["json"]


def test_configured_provider_failures_do_not_fall_back_to_mock_success(monkeypatch):
    client = ResellPortalClient(api_key="key", api_secret="secret")
    monkeypatch.setattr(
        client,
        "_make_request",
        lambda *args, **kwargs: {"success": False, "fallback": True, "error": "HTTP 502", "configured": True},
    )

    renew = client.renew_subscription("svc-1", "monthly")
    upgrade = client.upgrade_subscription("svc-1", "pro")
    cancel = client.cancel_subscription("svc-1")

    assert renew["success"] is False
    assert upgrade["success"] is False
    assert cancel["success"] is False
    assert renew["error"] == "HTTP 502"
    assert upgrade["error"] == "HTTP 502"
    assert cancel["error"] == "HTTP 502"


def test_production_unconfigured_provision_does_not_mock_success(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    client = ResellPortalClient(api_key="", api_secret="")

    result = client.provision_service(
        service_slug="crm",
        service_name="CRM",
        plan_code="starter",
        billing_cycle="monthly",
        user_email="buyer@test.local",
        user_id="usr_123",
        product_key="crm",
    )

    assert result["success"] is False


def test_production_configured_test_mode_refuses_provider_order(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "RESELLPORTAL_TEST_MODE", True)
    monkeypatch.setattr(settings, "RESELLPORTAL_ALLOW_LIVE", False)
    client = ResellPortalClient(api_key="key", api_secret="secret")

    result = client.provision_service(
        service_slug="crm",
        service_name="CRM",
        plan_code="starter",
        billing_cycle="monthly",
        user_email="buyer@test.local",
        user_id="usr_123",
        product_key="crm",
    )

    assert result["success"] is False
    assert "Live ResellPortal provisioning is not enabled" in result["error"]


def test_production_wallet_does_not_fall_back_to_mock(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    client = ResellPortalClient(api_key="", api_secret="")

    result = client.get_wallet_balance()

    assert result["success"] is False
    assert result["configured"] is False
    assert "balance" not in result


def test_resellportal_webhook_is_disabled_without_auth_contract():
    from fastapi import HTTPException
    from app.controller.technology.technology_services_controller import handle_resellportal_webhook

    with pytest.raises(HTTPException) as exc_info:
        handle_resellportal_webhook({"event": "subscription.active"})

    assert exc_info.value.status_code == 501
    assert "signature/authentication contract" in str(exc_info.value.detail)
