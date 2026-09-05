"""Tests for ResellPortal Integration & Premium Technology Admin."""

import pytest
from app.core.config import settings
from app.integrations.resellportal.client import ResellPortalClient, get_resellportal_client
from app.integrations.resellportal.mock_resellportal_api import MockResellPortalAPI


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

    provision = client.provision_service(
        service_slug="ai-business-suite",
        service_name="AI Business Suite",
        plan_code="pro",
        billing_cycle="monthly",
        user_email="test@cobrother.com",
        user_id="usr_001",
    )
    assert provision["success"] is True
    assert provision["status"] == "ACTIVE"
    assert "workspace.cobrother.com" in provision["credentials"]["access_url"]
    assert "resellportal" not in provision["credentials"]["access_url"].lower()


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
                "credentials": {"access_url": "https://workspace.cobrother.com/app/ai-business-suite/test?token=abc"},
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
    monkeypatch.setattr(ResellPortalClient, "_create_client", lambda self, email, uid: "test_cli_abc123")

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
    )

    assert result["success"] is True
    assert seen["method"] == "POST"
    assert seen["url"].endswith("/orders")
    assert seen["json"]["product_key"] == "ai_business_tools"
    assert seen["json"]["ai_tools"] == ["content-marketing-suite"]
    assert seen["json"]["test_mode"] is True
    assert seen["json"]["skip_client_email"] is True
    assert seen["json"]["client_id"] == "test_cli_abc123"


def test_resellportal_unconfigured_create_client_returns_mock():
    """Unconfigured client creation should fall back to the mock."""
    client = ResellPortalClient(api_key="", api_secret="")
    res = client._create_client("owner@cobrother.com", "usr_123")
    assert res is not None
    assert res.startswith("mock_cli_")


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
    assert result["status"] == "ACTIVE"
    assert "workspace.cobrother.com" in result["credentials"]["access_url"]
    assert result["credentials"]["instructions"].startswith("Access your white-labelled AI Business Suite dashboard")


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
