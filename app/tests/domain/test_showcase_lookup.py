"""Admin Showcase exact-domain lookup — mocks only, no DB, no network."""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

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
    assert result["item"]["id"] == str(saved_id)
    assert result["item"]["isSelected"] is False
    svc._repo.upsert_by_domain_name.assert_awaited_once()


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
