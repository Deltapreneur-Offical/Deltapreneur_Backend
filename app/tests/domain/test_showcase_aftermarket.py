"""Showcase Aftermarket (Afternic/Sedo) support — Phase A, mocks only.

Covers:

* ``_classify_items`` managed-only rule — aftermarket candidates must exceed the
  ₹5L managed-acquisition threshold (they must never reach normal checkout).
* ``_make_row`` source persistence (afternic / sedo / registry) + snapshot marker.
* ``_aftermarket_scan_for_label`` (Afternic preferred, Sedo fallback, filtering).
* ``generate_candidates`` keyword-mode aftermarket merge + below-threshold reject.
* ``select_domain`` aftermarket publish path (aftermarket price + managed gate).
* ``refresh_selected`` aftermarket revalidation.
* ``OpenProviderManagedCartService.confirm`` — aftermarket items quote from the
  live aftermarket check and never through GetPrice.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AppException


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

from app.service.domain.showcase_domain_service import ShowcaseDomainService


DEFAULT_CFG = {
    "enabled": False,
    "seed_labels": ["batterify"],
    "allowed_tlds": ["com", "ai", "io", "co"],
    "max_selected": 50,
    "refresh_interval_hours": 6,
    "last_refresh_at": None,
    "generation_lock": False,
}


def _item(fqdn: str, *, available: bool = True, premium: bool = True,
          price: float = 100.0, provider: str | None = None) -> dict:
    name, _, tld = fqdn.partition(".")
    item = {
        "domain": fqdn,
        "name": name,
        "tld": f".{tld}",
        "available": available,
        "isPremium": premium,
        "registrationPrice": price,
        "renewalPrice": price * 2,
        "registryTier": "premium" if premium else "standard",
        "currency": "INR",
    }
    if provider:
        item["_premium_provider"] = provider
    return item


def _raw_registry(fqdn: str, *, status: str = "active", premium: bool = False,
                  price: float = 100.0) -> dict:
    name, _, tld = fqdn.partition(".")
    return {
        "domain": fqdn,
        "name": name,
        "extension": tld,
        "status": status,
        "is_premium": premium,
        "price": {"reseller": {"price": price, "currency": "INR"}},
    }


def _raw_aftermarket(fqdn: str, provider: str, *, price: float = 600000.0) -> dict:
    name, _, tld = fqdn.partition(".")
    return {
        "domain": fqdn,
        "name": name,
        "extension": tld,
        "status": "free",
        "is_premium": True,
        "price": {"reseller": {"price": price, "currency": "INR"}},
        "_premium_provider": provider,
    }


def _attach_existing_table(svc) -> None:
    svc._session = MagicMock()
    svc._session.execute = AsyncMock(
        return_value=MagicMock(
            scalar=MagicMock(return_value="openprovider_showcase_domains")
        )
    )


# -------------------------------------------------- extension-less registry

def test_entry_tld_falls_back_to_fqdn():
    from app.service.domain import showcase_domain_service as svc_mod

    # OpenProvider sometimes omits `extension` — TLD must come from the FQDN.
    assert svc_mod._entry_tld({"domain": "batterify.com", "status": "active"}) == "com"
    assert svc_mod._entry_tld({"domain": "x.io", "extension": ".io"}) == "io"
    assert svc_mod._entry_tld({"domain": "noext", "status": "active"}) == ""


async def test_generate_aftermarket_with_extensionless_registry_rows():
    """Regression: OP returned entries WITHOUT `extension` (only domain+status),
    which silently disabled the aftermarket scan. The FQDN fallback must keep
    the aftermarket discovery working."""
    from app.integrations.openprovider import client as op
    from app.service.domain import showcase_domain_service as svc_mod

    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    _attach_existing_table(svc)
    svc._session.commit = AsyncMock()
    svc._repo = MagicMock()
    persisted: list = []
    svc._repo.get_by_domain_name = AsyncMock(return_value=None)
    svc._repo.upsert_by_domain_name = AsyncMock(side_effect=lambda row: persisted.append(row) or row)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value=DEFAULT_CFG)
    svc._config.claim_generation_lock = AsyncMock(return_value=True)
    svc._config.release_generation_lock = AsyncMock()
    svc._config.update = AsyncMock()
    svc._config.is_cancel_requested = AsyncMock(return_value=False)
    svc._active_marketplace_fqdns = AsyncMock(return_value=set())
    svc.count_all = AsyncMock(return_value=1)

    # No `extension` key — exactly the real OpenProvider response shape.
    registry_taken = [
        {"domain": "batterify.com", "status": "active", "price": {"reseller": {"price": 100.0, "currency": "INR"}}},
        {"domain": "batterify.io", "status": "active", "price": {"reseller": {"price": 100.0, "currency": "INR"}}},
    ]
    aftermarket_raw = [_raw_aftermarket("batterify.com", "afternic", price=600000.0)]
    scan_calls: list[list[str]] = []

    async def fake_scan(label, exts):
        scan_calls.append(exts)
        return aftermarket_raw

    with patch.object(op, "_check_tld_batches", new=AsyncMock(return_value=registry_taken)), patch.object(
        svc_mod, "_aftermarket_scan_for_label", new=fake_scan
    ):
        result = await svc.generate_candidates(seed_labels=["batterify"], count=50)

    assert scan_calls == [["com", "io"]]
    assert result["candidates_added"] == 1
    assert persisted[0].source == "afternic"


# -------------------------------------------------------- classification rule

def test_classify_aftermarket_managed_only_rule():
    """Aftermarket domains are no longer filtered by managed threshold
    during discovery — the threshold only applies at checkout."""
    items = [
        _item("after.com", price=600000.0, provider="afternic"),  # aftermarket
        _item("cheap.com", price=400000.0, provider="sedo"),      # aftermarket, below old 5L
        _item("reg.com", price=600000.0),                          # registry
    ]
    picked, reasons = ShowcaseDomainService._classify_items(
        items,
        allowed_tlds=["com"],
        excluded_fqdns=set(),
        count=50,
    )
    # All three are now accepted — threshold was removed from discovery.
    assert [it["domain"] for it in picked] == ["cheap.com", "after.com", "reg.com"]
    assert reasons["below_managed_threshold"] == 0


# ------------------------------------------------------------- row building

def test_make_row_source_aftermarket():
    row = ShowcaseDomainService._make_row(
        "batterify", _item("batterify.com", price=600000.0, provider="afternic")
    )
    assert row.source == "afternic"
    assert (row.price_snapshot_json or {}).get("premiumProvider") == "afternic"

    reg = ShowcaseDomainService._make_row("x", _item("x.com", price=600000.0))
    assert reg.source == "registry"
    assert (reg.price_snapshot_json or {}).get("premiumProvider") is None


# ------------------------------------------------------- aftermarket scanner

@pytest.mark.asyncio
async def test_aftermarket_scan_prefers_afternic_and_filters(monkeypatch):
    from app.integrations.openprovider import client as op
    from app.service.domain import showcase_domain_service as svc_mod

    async def fake_check(name: str, ext: str, provider: str | None = None) -> dict:
        # Afternic returns premium for both exts -> both accepted as afternic.
        return {
            "status": "free", "is_premium": True,
            "extension": ext, "name": name, "domain": f"{name}.{ext}",
        }

    monkeypatch.setattr(op, "_check_domain_raw", fake_check)
    results = await svc_mod._aftermarket_scan_for_label("batterify", ["com", "io"])
    assert len(results) == 2
    assert all(r["_premium_provider"] == "afternic" for r in results)


@pytest.mark.asyncio
async def test_aftermarket_scan_falls_back_to_sedo(monkeypatch):
    from app.integrations.openprovider import client as op
    from app.service.domain import showcase_domain_service as svc_mod

    async def fake_check(name: str, ext: str, provider: str | None = None) -> dict:
        if provider == "afternic":
            return {
                "status": "free", "is_premium": False,
                "extension": ext, "name": name, "domain": f"{name}.{ext}",
            }
        return {
            "status": "free", "is_premium": True,
            "extension": ext, "name": name, "domain": f"{name}.{ext}",
        }

    monkeypatch.setattr(op, "_check_domain_raw", fake_check)
    results = await svc_mod._aftermarket_scan_for_label("batterify", ["com"])
    assert len(results) == 1
    assert results[0]["_premium_provider"] == "sedo"


# ------------------------------------------------------- keyword generation

async def test_generate_aftermarket_happy_path_persists_source():
    from app.integrations.openprovider import client as op
    from app.service.domain import showcase_domain_service as svc_mod

    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    _attach_existing_table(svc)
    svc._session.commit = AsyncMock()
    svc._repo = MagicMock()
    persisted: list = []
    svc._repo.get_by_domain_name = AsyncMock(return_value=None)
    svc._repo.upsert_by_domain_name = AsyncMock(side_effect=lambda row: persisted.append(row) or row)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value=DEFAULT_CFG)
    svc._config.claim_generation_lock = AsyncMock(return_value=True)
    svc._config.release_generation_lock = AsyncMock()
    svc._config.update = AsyncMock()
    svc._config.is_cancel_requested = AsyncMock(return_value=False)
    svc._active_marketplace_fqdns = AsyncMock(return_value=set())
    svc.count_all = AsyncMock(return_value=1)

    registry_taken = [_raw_registry("batterify.com", status="active")]
    aftermarket_raw = [_raw_aftermarket("batterify.com", "afternic", price=600000.0)]

    with patch.object(op, "_check_tld_batches", new=AsyncMock(return_value=registry_taken)), patch.object(
        svc_mod, "_aftermarket_scan_for_label", new=AsyncMock(return_value=aftermarket_raw)
    ):
        result = await svc.generate_candidates(seed_labels=["batterify"], count=50)

    assert result["candidates_added"] == 1
    assert len(persisted) == 1
    assert persisted[0].source == "afternic"
    assert persisted[0].is_selected is False
    assert persisted[0].create_price_inr == pytest.approx(660000.0)  # 600k × 1.1 margin


async def test_generate_aftermarket_below_threshold_now_accepted():
    """Managed threshold no longer filters during discovery — even
    cheap aftermarket domains are accepted into the pool."""
    from app.integrations.openprovider import client as op
    from app.service.domain import showcase_domain_service as svc_mod

    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    _attach_existing_table(svc)
    svc._session.commit = AsyncMock()
    svc._repo = MagicMock()
    persisted: list = []
    svc._repo.get_by_domain_name = AsyncMock(return_value=None)
    svc._repo.upsert_by_domain_name = AsyncMock(side_effect=lambda row: persisted.append(row) or row)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value=DEFAULT_CFG)
    svc._config.claim_generation_lock = AsyncMock(return_value=True)
    svc._config.release_generation_lock = AsyncMock()
    svc._config.update = AsyncMock()
    svc._config.is_cancel_requested = AsyncMock(return_value=False)
    svc._active_marketplace_fqdns = AsyncMock(return_value=set())
    svc.count_all = AsyncMock(return_value=0)

    registry_taken = [_raw_registry("cheap.com", status="active")]
    aftermarket_raw = [_raw_aftermarket("cheap.com", "sedo", price=300000.0)]

    with patch.object(op, "_check_tld_batches", new=AsyncMock(return_value=registry_taken)), patch.object(
        svc_mod, "_aftermarket_scan_for_label", new=AsyncMock(return_value=aftermarket_raw)
    ):
        result = await svc.generate_candidates(seed_labels=["cheap"], count=50)

    # Threshold removed — cheap.com is now accepted into the pool.
    assert result["candidates_added"] == 1
    assert len(persisted) == 1
    assert persisted[0].domain_name == "cheap.com"
    assert result["reasons"]["below_managed_threshold"] == 0


# ------------------------------------------------------------ select / tick

async def test_select_aftermarket_publishes_with_check_price():
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    _attach_existing_table(svc)
    row = ShowcaseDomainService._make_row(
        "batterify", _item("batterify.com", price=600000.0, provider="afternic")
    )
    row.is_selected = False
    svc._repo = MagicMock()
    svc._repo.get_by_id = AsyncMock(return_value=row)
    svc._repo.save = AsyncMock(side_effect=lambda r: r)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value=DEFAULT_CFG)
    svc._config.is_cancel_requested = AsyncMock(return_value=False)
    svc.count_selected = AsyncMock(return_value=0)
    svc._session.commit = AsyncMock()

    class FakeCheck:
        status = "available"
        unitPrice = 660000.0
        priceCurrency = "INR"
        priceSource = "openprovider_check"
        minPeriodYears = 1

    fake_reg_svc = MagicMock()
    fake_reg_svc.check_registration_domain = AsyncMock(return_value=FakeCheck())
    fake_reg_svc.quote_registration_period_price = AsyncMock(return_value={})

    with patch(
        "app.service.domain.domain_registration_service.DomainRegistrationService",
        return_value=fake_reg_svc,
    ):
        out = await svc.select_domain(row.id)

    assert out["isSelected"] is True
    assert row.source == "afternic"
    assert row.create_price_inr == 660000.0
    assert row.payable_inr > 660000.0
    # GetPrice must never be used for aftermarket items.
    fake_reg_svc.quote_registration_period_price.assert_not_awaited()


async def test_select_aftermarket_below_threshold_now_accepted():
    """Managed threshold removed — even cheap aftermarket domains can be
    published via Tick."""
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    _attach_existing_table(svc)
    svc._session.commit = AsyncMock()
    row = ShowcaseDomainService._make_row(
        "batterify", _item("batterify.com", price=400000.0, provider="afternic")
    )
    row.is_selected = False
    svc._repo = MagicMock()
    svc._repo.get_by_id = AsyncMock(return_value=row)
    svc._repo.save = AsyncMock(side_effect=lambda r: r)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value=DEFAULT_CFG)
    svc._config.is_cancel_requested = AsyncMock(return_value=False)
    svc.count_selected = AsyncMock(return_value=0)

    class FakeCheck:
        status = "available"
        unitPrice = 400000.0
        priceCurrency = "INR"
        minPeriodYears = 1
        priceSource = "aftermarket_check"

    fake_reg_svc = MagicMock()
    fake_reg_svc.check_registration_domain = AsyncMock(return_value=FakeCheck())

    with patch(
        "app.service.domain.domain_registration_service.DomainRegistrationService",
        return_value=fake_reg_svc,
    ):
        result = await svc.select_domain(row.id)

    # Threshold removed — domain is now accepted and published.
    assert row.is_selected is True
    assert row.available is True
    assert row.create_price_inr == 400000.0


# ------------------------------------------------------------- refresh

async def test_refresh_aftermarket_uses_check_price():
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    _attach_existing_table(svc)
    row = ShowcaseDomainService._make_row(
        "batterify", _item("batterify.com", price=600000.0, provider="afternic")
    )
    row.is_selected = True
    svc._repo = MagicMock()
    svc._repo.list_selected_for_refresh = AsyncMock(return_value=[row])
    svc._repo.save = AsyncMock(side_effect=lambda r: r)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value=DEFAULT_CFG)
    svc._config.claim_generation_lock = AsyncMock(return_value=True)
    svc._config.release_generation_lock = AsyncMock()
    svc._config.update = AsyncMock()
    svc._config.is_cancel_requested = AsyncMock(return_value=False)
    svc.count_selected = AsyncMock(return_value=1)
    svc._session.commit = AsyncMock()

    class FakeCheck:
        status = "available"
        unitPrice = 660000.0
        priceCurrency = "INR"

    fake_reg_svc = MagicMock()
    fake_reg_svc.check_registration_domain = AsyncMock(return_value=FakeCheck())
    fake_reg_svc.quote_registration_period_price = AsyncMock(return_value={})

    with patch(
        "app.service.domain.domain_registration_service.DomainRegistrationService",
        return_value=fake_reg_svc,
    ):
        result = await svc.refresh_selected()

    assert result["refreshed"] == 1
    assert result["removed_unavailable"] == 0
    assert row.create_price_inr == 660000.0
    fake_reg_svc.quote_registration_period_price.assert_not_awaited()


# ------------------------------------------------- managed confirm routing

@pytest.mark.asyncio
async def test_managed_confirm_aftermarket_never_uses_getprice():
    from app.service.cart.openprovider_managed_cart_service import (
        OpenProviderManagedCartService,
    )

    svc = OpenProviderManagedCartService.__new__(OpenProviderManagedCartService)
    cart_item = MagicMock()
    cart_item.product_type = "DOMAIN_REGISTRATION"
    cart_item.metadata_json = {
        "domainName": "batterify.com",
        "tld": "com",
        "premiumProvider": "afternic",
        "price": 660000.0,
        "period": 1,
    }
    svc._cart = MagicMock()
    svc._cart.get_by_user = AsyncMock(return_value=[cart_item])
    svc._cart.save = AsyncMock(side_effect=lambda it: it)
    svc._cart.delete_by_id = AsyncMock()
    svc._acq = MagicMock()
    svc._acq.create = AsyncMock()
    svc._session = MagicMock()
    svc._session.commit = AsyncMock()
    svc._session.refresh = AsyncMock()

    class FakeCheck:
        status = "available"
        unitPrice = 660000.0
        priceCurrency = "INR"
        priceSource = "openprovider_check"
        minPeriodYears = 1

    fake_reg_svc = MagicMock()
    fake_reg_svc.check_registration_domain = AsyncMock(return_value=FakeCheck())

    with patch(
        "app.service.domain.domain_registration_service.DomainRegistrationService",
        return_value=fake_reg_svc,
    ), patch(
        "app.service.cart.cart_service.CartService",
    ) as mock_cart_svc, patch(
        "app.service.cart.openprovider_managed_cart_service.MailService.send_premium_marketplace_buyer_confirmation_email",
        new=AsyncMock(),
    ), patch(
        "app.service.cart.openprovider_managed_cart_service.MailService.send_premium_marketplace_admin_alert_email",
        new=AsyncMock(),
    ), patch.object(
        OpenProviderManagedCartService, "_notify_user", new=AsyncMock()
    ), patch.object(
        OpenProviderManagedCartService, "_notify_admins", new=AsyncMock()
    ):
        mock_cart_svc.return_value._apply_registration_period_quote = AsyncMock()
        result = await svc.confirm(
            MagicMock(),
            full_name="Buyer",
            email="buyer@example.com",
            phone="123",
            message="acquisition",
        )

    mock_cart_svc.return_value._apply_registration_period_quote.assert_not_awaited()
    fake_reg_svc.check_registration_domain.assert_awaited_once()
    assert cart_item.metadata_json["price"] == 660000.0
    assert cart_item.metadata_json["isManagedAcquisition"] is True
    assert cart_item.metadata_json["premiumProvider"] == "afternic"
    assert result["success"] is True
    assert float(result["payableInr"]) > 660000.0


# ---------------------------------------------------------------------------
# Soft-delete revive — a deleted domain must be re-discoverable by Generate
# ---------------------------------------------------------------------------


def test_upsert_revives_soft_deleted_row_instead_of_silent_skip():
    """Regression: a soft-deleted row still holds the unique domain_name key.

    ``on_conflict_do_nothing`` used to silently no-op, so Generate reported
    ``candidates_added=1`` while the candidate never reappeared and the list
    stayed empty. The upsert must instead DO-UPDATE the deleted row back to a
    live candidate (is_deleted=False, deleted_at=None) with fresh data, and
    must NOT touch a live (non-deleted) conflicting row.
    """
    from datetime import datetime, timezone

    from sqlalchemy.orm import Session

    from app.entity.domain.openprovider_showcase_entity import (
        OpenProviderShowcaseDomain,
    )
    from app.repository.showcase_domain_repository import (
        ShowcaseDomainRepository,
    )

    now = datetime.now(timezone.utc)

    class FakeResult:
        def scalar_one_or_none(self):
            return "7d834cf2-c649-4546-a51c-6858d8b51b36"

    session = MagicMock(spec=Session)
    session.execute = AsyncMock(return_value=FakeResult())

    row = OpenProviderShowcaseDomain(
        id="7d834cf2-c649-4546-a51c-6858d8b51b36",
        domain_name="batterify.com",
        label="batterify",
        tld="com",
        is_premium=True,
        source="afternic",
        create_price_inr=33070261.62,
        renewal_price_inr=0.0,
        payable_inr=33070261.62,
        price_snapshot_json={"premiumProvider": "afternic"},
        available=True,
        last_checked_at=now,
        is_selected=False,
        display_order=0,
    )

    repo = ShowcaseDomainRepository(session)
    result = asyncio_run(repo.upsert_by_domain_name(row))

    assert result is row
    stmt = session.execute.await_args.args[0]

    sql = str(stmt)
    assert "INSERT INTO" in sql
    # Must use DO UPDATE (not DO NOTHING) so the deleted row is revived.
    assert "ON CONFLICT" in sql
    assert "DO UPDATE" in sql
    assert "DO NOTHING" not in sql
    # The update must be scoped to soft-deleted rows only.
    assert "is_deleted is true" in sql.lower()
    # The revive must clear the soft-delete markers with fresh candidate data.
    assert "deleted_at" in sql


def asyncio_run(coro):
    import asyncio

    return asyncio.get_event_loop().run_until_complete(coro)
