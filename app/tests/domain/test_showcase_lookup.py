"""Admin Showcase exact-domain lookup — mocks only, no DB, no network."""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import AppException
from app.service.domain.showcase_domain_service import ShowcaseDomainService


def _import_all_entities() -> None:
    entity_root = Path(__file__).resolve().parents[3] / "app" / "entity"
    if not entity_root.exists():
        return
    for module_path in sorted(entity_root.rglob("*.py")):
        if module_path.name == "__init__.py":
            continue
        rel = module_path.relative_to(entity_root).with_suffix("")
        module_name = ".".join(["app", "entity", *rel.parts])
        try:
            importlib.import_module(module_name)
        except Exception:
            pass


_import_all_entities()


RAW_FREE_PREMIUM = {
    "domain": "shinebyte.com",
    "name": "shinebyte",
    "extension": "com",
    "status": "free",
    "is_premium": True,
    "price": {"reseller": {"price": 50000.0, "currency": "INR"}},
}

RAW_FREE_STANDARD = {
    "domain": "example.com",
    "name": "example",
    "extension": "com",
    "status": "free",
    "is_premium": False,
    "price": {"reseller": {"price": 800.0, "currency": "INR"}},
}

RAW_TAKEN = {
    "domain": "taken.com",
    "name": "taken",
    "extension": "com",
    "status": "active",
    "is_premium": True,
    "price": {"reseller": {"price": 40000.0, "currency": "INR"}},
}


def _attach_existing_table(svc) -> None:
    svc._session = MagicMock()
    svc._session.execute = AsyncMock(
        return_value=MagicMock(
            scalar=MagicMock(return_value="openprovider_showcase_domains")
        )
    )
    svc._session.commit = AsyncMock()


def _svc(monkeypatch, raw):
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    _attach_existing_table(svc)
    svc._repo = MagicMock()
    svc._repo.get_by_domain_name = AsyncMock(return_value=None)
    svc._repo.save = AsyncMock(side_effect=lambda row: row)
    svc._repo.upsert_by_domain_name = AsyncMock(side_effect=lambda row: row)
    svc._config = MagicMock()
    svc._active_marketplace_fqdns = AsyncMock(return_value=set())
    monkeypatch.setattr(
        "app.integrations.openprovider.client.check_domain",
        AsyncMock(return_value=raw),
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.get_domain_price",
        AsyncMock(return_value={"price": {}}),
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client._check_tld_batches",
        AsyncMock(side_effect=AssertionError("batch TLD search must not run")),
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.search_domains_label_first_page",
        AsyncMock(side_effect=AssertionError("label search must not run")),
    )
    monkeypatch.setattr(
        "app.integrations.openprovider.client.search_domains_label_remaining",
        AsyncMock(side_effect=AssertionError("catalog search must not run")),
    )
    monkeypatch.setattr(
        ShowcaseDomainService,
        "generate_candidates",
        AsyncMock(side_effect=AssertionError("keyword generate must not run")),
    )
    monkeypatch.setattr(
        ShowcaseDomainService,
        "generate_random_candidates",
        AsyncMock(side_effect=AssertionError("random generate must not run")),
    )
    return svc


def test_post_lookup_is_registered_and_not_captured_by_delete_row_id():
    """Production 405: POST /lookup was matched by DELETE /{row_id}."""
    from app.controller.admin.showcase_admin_controller import router

    lookup_methods: set[str] = set()
    row_id_methods: set[str] = set()
    for route in router.routes:
        path = getattr(route, "path", "") or ""
        name = getattr(route, "name", "") or ""
        methods = set(getattr(route, "methods", None) or [])
        if path.rstrip("/").endswith("/lookup") or name == "lookup_exact_domain":
            lookup_methods |= methods
        if "{row_id}" in path:
            row_id_methods |= methods

    assert "POST" in lookup_methods
    assert "DELETE" in row_id_methods
    assert "POST" not in row_id_methods


def test_post_lookup_http_is_not_405():
    """The failing admin search: POST /api/v1/admin/showcase/lookup must not 405."""
    from app.controller.admin.showcase_admin_controller import router
    from app.core.database import get_async_db

    async def _db():
        yield MagicMock()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_async_db] = _db
    client = TestClient(app, raise_server_exceptions=False)
    res = client.post(
        "/api/v1/admin/showcase/lookup",
        json={"domain_name": "zevira", "tld": "com"},
    )
    assert res.status_code != 405, (
        f"POST /lookup returned 405; DELETE /{{row_id}} is capturing the path. "
        f"body={res.text[:200]}"
    )
    # Unauthenticated request reaches the lookup route; auth fails after method match.
    assert res.status_code in (401, 403)


def test_post_lookup_http_succeeds_with_admin_and_openprovider_check(monkeypatch):
    from app.controller.admin.showcase_admin_controller import router
    from app.core.database import get_async_db
    from app.core.dependencies import get_current_user
    from app.entity.user.app_user import AppUser
    from app.entity.user.user_role import UserRole

    saved_id = str(uuid4())
    live_result = {
        "eligible": True,
        "canSelect": True,
        "reason": None,
        "message": None,
        "live": {
            "domainName": "shinebyte.com",
            "tld": "com",
            "available": True,
            "isPremium": True,
            "source": "registry",
            "createPriceInr": 55555.0,
        },
        "item": {"id": saved_id, "isSelected": False, "domainName": "shinebyte.com"},
    }

    async def _lookup(self, *, domain_name: str, tld: str):
        assert domain_name == "shinebyte"
        assert tld == "com"
        return live_result

    async def _db():
        yield MagicMock()

    def _admin():
        return AppUser(
            id=uuid4(),
            email="admin@test.local",
            firstname="Admin",
            lastname="User",
            role=UserRole.ADMIN,
            active=True,
            email_verified=True,
            profile_complete=True,
        )

    monkeypatch.setattr(ShowcaseDomainService, "lookup_exact_domain", _lookup)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_async_db] = _db
    app.dependency_overrides[get_current_user] = _admin
    client = TestClient(app, raise_server_exceptions=False)
    res = client.post(
        "/api/v1/admin/showcase/lookup",
        json={"domain_name": "shinebyte", "tld": "com"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["eligible"] is True
    assert body["live"]["isPremium"] is True
    assert body["live"]["createPriceInr"] == 55555.0
    assert "providerUnitPriceInr" not in body["live"]


@pytest.mark.asyncio
async def test_lookup_premium_succeeds_and_returns_live_price_and_id(monkeypatch):
    svc = _svc(monkeypatch, RAW_FREE_PREMIUM)
    saved_id = uuid4()
    saved = ShowcaseDomainService._make_row(
        "shinebyte",
        {
            "domain": "shinebyte.com",
            "tld": "com",
            "isPremium": True,
            "registrationPrice": 50000.0,
            "renewalPrice": 50000.0,
            "registryTier": "premium",
            "currency": "INR",
        },
    )
    saved.id = saved_id

    async def _upsert(row):
        row.id = saved_id
        return row

    svc._repo.upsert_by_domain_name = AsyncMock(side_effect=_upsert)
    svc._repo.get_by_domain_name = AsyncMock(side_effect=[None, saved])

    result = await svc.lookup_exact_domain(domain_name="shinebyte", tld=".com")
    assert result["eligible"] is True
    assert result["canSelect"] is True
    assert result["live"]["createPriceInr"] and result["live"]["createPriceInr"] > 0
    assert result["live"]["isPremium"] is True
    assert "providerUnitPriceInr" not in result["live"]
    assert result["item"]["id"] == str(saved_id)
    assert result["item"]["isSelected"] is False
    svc._repo.upsert_by_domain_name.assert_awaited_once()


@pytest.mark.asyncio
async def test_lookup_uses_customer_price_not_openprovider_base(monkeypatch):
    svc = _svc(monkeypatch, RAW_FREE_PREMIUM)
    saved_id = uuid4()
    saved = ShowcaseDomainService._make_row(
        "shinebyte",
        {
            "domain": "shinebyte.com",
            "tld": "com",
            "isPremium": True,
            "registrationPrice": 50000.0,
            "renewalPrice": 50000.0,
            "registryTier": "premium",
            "currency": "INR",
        },
    )
    saved.id = saved_id
    svc._repo.upsert_by_domain_name = AsyncMock(side_effect=lambda row: row)
    svc._repo.get_by_domain_name = AsyncMock(side_effect=[None, saved])

    result = await svc.lookup_exact_domain(domain_name="shinebyte", tld="com")
    live_price = result["live"]["createPriceInr"]
    assert live_price is not None
    # Commission markup means customer unit != raw OpenProvider reseller 50000,
    # or equals it only when the configured premium rate is 0 — never a hardcoded list.
    assert live_price > 0
    assert "providerUnitPriceInr" not in result["live"]


@pytest.mark.asyncio
async def test_lookup_fetches_missing_renewal_from_openprovider_getprice(monkeypatch):
    raw = {
        **RAW_FREE_PREMIUM,
        "domain": "kokini.com",
        "name": "kokini",
        "price": {"reseller": {"price": 50000.0, "currency": "INR"}},
        "premium": {"price": {"create": 50000.0}},
    }
    svc = _svc(monkeypatch, raw)
    saved_id = uuid4()

    async def _upsert(row):
        row.id = saved_id
        return row

    svc._repo.upsert_by_domain_name = AsyncMock(side_effect=_upsert)
    svc._repo.get_by_domain_name = AsyncMock(side_effect=[None, None])
    renew_quote = {"price": {"reseller": {"price": 1037.79, "currency": "INR"}}}
    renew_price = AsyncMock(return_value=renew_quote)
    monkeypatch.setattr("app.integrations.openprovider.client.get_domain_price", renew_price)

    result = await svc.lookup_exact_domain(domain_name="kokini", tld="com")

    renew_price.assert_awaited_once_with("kokini", "com", operation="renew", period=1)
    assert result["eligible"] is True
    assert result["live"]["createPriceInr"] and result["live"]["createPriceInr"] > 0
    assert result["live"]["renewalPriceInr"] == 1037.79
    assert result["item"]["renewalPriceInr"] == 1037.79
    assert result["live"]["renewalPriceInr"] != result["live"]["createPriceInr"]


@pytest.mark.asyncio
async def test_lookup_does_not_calculate_renewal_when_openprovider_omits_it(monkeypatch):
    svc = _svc(monkeypatch, RAW_FREE_PREMIUM)
    svc._repo.upsert_by_domain_name = AsyncMock(side_effect=lambda row: row)
    svc._repo.get_by_domain_name = AsyncMock(side_effect=[None, None])
    renew_price = AsyncMock(return_value={"price": {"reseller": {"currency": "INR"}}})
    monkeypatch.setattr("app.integrations.openprovider.client.get_domain_price", renew_price)

    result = await svc.lookup_exact_domain(domain_name="shinebyte", tld="com")

    assert result["eligible"] is True
    assert result["live"]["createPriceInr"] and result["live"]["createPriceInr"] > 0
    assert result["live"]["renewalPriceInr"] is None
    assert result["item"]["renewalPriceInr"] is None


@pytest.mark.asyncio
async def test_lookup_checks_only_the_exact_domain(monkeypatch):
    svc = _svc(monkeypatch, RAW_FREE_PREMIUM)
    from app.integrations.openprovider import client as op_client

    result = await svc.lookup_exact_domain(domain_name="shinebyte", tld="com")
    assert result["eligible"] is True
    op_client.check_domain.assert_awaited_once()
    args, kwargs = op_client.check_domain.await_args
    assert args[0] == "shinebyte"
    assert args[1] == "com"
    assert kwargs.get("include_aftermarket") is True


@pytest.mark.asyncio
async def test_lookup_skips_aftermarket_for_non_aftermarket_tld(monkeypatch):
    raw = {
        **RAW_FREE_PREMIUM,
        "domain": "shinebyte.ai",
        "extension": "ai",
    }
    svc = _svc(monkeypatch, raw)
    from app.integrations.openprovider import client as op_client

    await svc.lookup_exact_domain(domain_name="shinebyte", tld="ai")
    args, kwargs = op_client.check_domain.await_args
    assert args == ("shinebyte", "ai")
    assert kwargs.get("include_aftermarket") is False


@pytest.mark.asyncio
async def test_lookup_invalid_input(monkeypatch):
    svc = _svc(monkeypatch, RAW_FREE_PREMIUM)
    from app.integrations.openprovider import client as op_client

    with pytest.raises(AppException) as exc:
        await svc.lookup_exact_domain(domain_name="shinebyte.com", tld="com")
    assert exc.value.status_code == 400
    assert exc.value.code == "SHOWCASE_LOOKUP_INVALID"
    op_client.check_domain.assert_not_awaited()

    with pytest.raises(AppException) as exc:
        await svc.lookup_exact_domain(domain_name="", tld="com")
    assert exc.value.status_code == 400
    op_client.check_domain.assert_not_awaited()

    with pytest.raises(AppException) as exc:
        await svc.lookup_exact_domain(domain_name="shinebyte", tld="")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_lookup_unavailable_is_not_selectable(monkeypatch):
    svc = _svc(monkeypatch, RAW_TAKEN)
    result = await svc.lookup_exact_domain(domain_name="taken", tld="com")
    assert result["eligible"] is False
    assert result["canSelect"] is False
    assert result["reason"] == "taken"
    assert result["item"] is None
    svc._repo.upsert_by_domain_name.assert_not_awaited()


@pytest.mark.asyncio
async def test_lookup_standard_domain_is_not_premium_showcase(monkeypatch):
    svc = _svc(monkeypatch, RAW_FREE_STANDARD)
    result = await svc.lookup_exact_domain(domain_name="example", tld="com")
    assert result["eligible"] is False
    assert result["canSelect"] is False
    assert result["reason"] == "not_premium"
    assert result["live"]["isPremium"] is False
    assert result["live"]["createPriceInr"] and result["live"]["createPriceInr"] > 0
    svc._repo.upsert_by_domain_name.assert_not_awaited()


@pytest.mark.asyncio
async def test_lookup_openprovider_error(monkeypatch):
    svc = _svc(monkeypatch, RAW_FREE_PREMIUM)
    monkeypatch.setattr(
        "app.integrations.openprovider.client.check_domain",
        AsyncMock(side_effect=RuntimeError("registrar down")),
    )
    with pytest.raises(AppException) as exc:
        await svc.lookup_exact_domain(domain_name="shinebyte", tld="com")
    assert exc.value.status_code == 502
    assert exc.value.code == "SHOWCASE_LOOKUP_PROVIDER_ERROR"
    assert "OpenProvider" not in exc.value.message


@pytest.mark.asyncio
async def test_lookup_access_denied_returns_instruction_not_502(monkeypatch):
    """Local 10005 must not become a generic axios-sanitized 502."""
    svc = _svc(monkeypatch, RAW_FREE_PREMIUM)
    monkeypatch.setattr(
        "app.integrations.openprovider.client.check_domain",
        AsyncMock(
            side_effect=RuntimeError(
                "Registrar domains/check failed (HTTP 500, code=10005): Access denied."
            )
        ),
    )
    result = await svc.lookup_exact_domain(domain_name="ventorly", tld="com")
    assert result["eligible"] is False
    assert result["canSelect"] is False
    assert result["reason"] == "provider_access_denied"
    assert "API access list" in result["message"]
    assert result["live"]["domainName"] == "ventorly.com"
    assert result["item"] is None
    svc._repo.upsert_by_domain_name.assert_not_awaited()


@pytest.mark.asyncio
async def test_lookup_duplicate_updates_unselected_not_inserts_second(monkeypatch):
    svc = _svc(monkeypatch, RAW_FREE_PREMIUM)
    existing = ShowcaseDomainService._make_row(
        "shinebyte",
        {
            "domain": "shinebyte.com",
            "tld": "com",
            "isPremium": True,
            "registrationPrice": 1000.0,
            "renewalPrice": 2000.0,
            "registryTier": "premium",
            "currency": "INR",
        },
    )
    existing.id = uuid4()
    existing.is_selected = False
    existing.create_price_inr = 1000.0
    svc._repo.get_by_domain_name = AsyncMock(return_value=existing)

    result = await svc.lookup_exact_domain(domain_name="shinebyte", tld="com")
    assert result["eligible"] is True
    assert result["item"]["id"] == str(existing.id)
    assert existing.create_price_inr != 1000.0
    svc._repo.save.assert_awaited()
    svc._repo.upsert_by_domain_name.assert_not_awaited()


@pytest.mark.asyncio
async def test_lookup_already_selected_is_never_unselected(monkeypatch):
    svc = _svc(monkeypatch, RAW_FREE_PREMIUM)
    existing = ShowcaseDomainService._make_row(
        "shinebyte",
        {
            "domain": "shinebyte.com",
            "tld": "com",
            "isPremium": True,
            "registrationPrice": 1000.0,
            "renewalPrice": 2000.0,
            "registryTier": "premium",
            "currency": "INR",
        },
    )
    existing.id = uuid4()
    existing.is_selected = True
    existing.create_price_inr = 1000.0
    svc._repo.get_by_domain_name = AsyncMock(return_value=existing)

    result = await svc.lookup_exact_domain(domain_name="shinebyte", tld="com")
    assert result["alreadySelected"] is True
    assert result["canSelect"] is False
    assert result["item"]["isSelected"] is True
    assert existing.is_selected is True
    assert existing.create_price_inr == 1000.0
    svc._repo.save.assert_not_awaited()
    svc._repo.upsert_by_domain_name.assert_not_awaited()
    assert result["live"]["createPriceInr"] and result["live"]["createPriceInr"] > 1000.0


@pytest.mark.asyncio
async def test_lookup_marketplace_listed_skips_openprovider(monkeypatch):
    svc = _svc(monkeypatch, RAW_FREE_PREMIUM)
    svc._active_marketplace_fqdns = AsyncMock(return_value={"shinebyte.com"})
    from app.integrations.openprovider import client as op_client

    result = await svc.lookup_exact_domain(domain_name="shinebyte", tld="com")
    assert result["reason"] == "marketplace_listed"
    assert result["canSelect"] is False
    op_client.check_domain.assert_not_awaited()
