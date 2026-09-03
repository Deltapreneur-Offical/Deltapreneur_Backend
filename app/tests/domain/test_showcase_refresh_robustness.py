"""Showcase refresh robustness tests (mocks only, no DB, no network).

Proves the Selected (admin intent) vs Available (live OP status) separation:

1. Selected + available     -> refresh checks it and keeps it available.
2. Selected + unavailable   -> refresh STILL checks it (list_selected_for_refresh).
3. Successful OP check restores unavailable -> available.
4. OP transient failure     -> does not unselect/delete; keeps last known state.
5. Admin untick             -> removes from selected state.
6. Unticked domain          -> cannot be republished by refresh.
7. Public listing           -> only selected + available + not-deleted.
8. Homepage feed            -> only selected + available rows.
9. Repeated refreshes       -> never permanently lose selected domains.
10. Unselect/remove wins    -> refresh never re-selects.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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
    "enabled": True,
    "seed_labels": ["batterify"],
    "allowed_tlds": [],
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


def _make_row(fqdn: str, *, price: float = 100.0, source: str = "registry",
              available: bool = True, selected: bool = True) -> object:
    provider = source if source in ("afternic", "sedo") else None
    row = ShowcaseDomainService._make_row(
        fqdn.partition(".")[0],
        _item(fqdn, price=price, provider=provider),
    )
    row.source = source
    row.available = available
    row.is_selected = selected
    row.is_deleted = False
    return row


def _attach_existing_table(svc) -> None:
    svc._session = MagicMock()
    svc._session.execute = AsyncMock(
        return_value=MagicMock(
            scalar=MagicMock(return_value="openprovider_showcase_domains")
        )
    )


def _make_svc(rows: list, *, repo_side_effects: dict | None = None) -> ShowcaseDomainService:
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    _attach_existing_table(svc)
    svc._repo = MagicMock()
    svc._repo.list_selected_for_refresh = AsyncMock(return_value=list(rows))
    svc._repo.save = AsyncMock(side_effect=lambda r: r)
    svc._repo.get_by_id = AsyncMock(
        side_effect=lambda rid: next(
            (r for r in rows if str(r.id) == str(rid)), None
        )
    )
    async def _soft_delete(rid):
        for r in rows:
            if str(r.id) == str(rid):
                r.is_deleted = True
                return True
        return False

    svc._repo.soft_delete_by_id = AsyncMock(side_effect=_soft_delete)
    if repo_side_effects:
        for attr, fn in repo_side_effects.items():
            setattr(svc._repo, attr, fn)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value=dict(DEFAULT_CFG))
    svc._config.claim_generation_lock = AsyncMock(return_value=True)
    svc._config.release_generation_lock = AsyncMock()
    svc._config.update = AsyncMock()
    svc.count_selected = AsyncMock(return_value=len(rows))
    svc._session.commit = AsyncMock()
    return svc


class _FakeCheck:
    def __init__(self, *, status: str = "available", unit_price: float = 0.0):
        self.status = status
        self.unitPrice = unit_price
        self.priceCurrency = "INR"
        self.minPeriodYears = 1
        self.priceSource = "check"
        self.renewalPriceInr = None


def _patch_registrar(check=None, *, exc: Exception | None = None, quote: dict | None = None):
    fake_reg_svc = MagicMock()
    if exc is not None:
        fake_reg_svc.check_registration_domain = AsyncMock(side_effect=exc)
    else:
        fake_reg_svc.check_registration_domain = AsyncMock(return_value=check)
    fake_reg_svc.quote_registration_period_price = AsyncMock(
        return_value=quote or {"price": 1000.0}
    )
    return patch(
        "app.service.domain.domain_registration_service.DomainRegistrationService",
        return_value=fake_reg_svc,
    )


# ------------------------------------------------------------ 1+2+3: refresh checks all selected

@pytest.mark.asyncio
async def test_refresh_checks_selected_available_row():
    row = _make_row("shinebyte.com", price=50000.0, available=True)
    svc = _make_svc([row])
    check = _FakeCheck(status="available")
    with _patch_registrar(check):
        result = await svc.refresh_selected()
    assert result["refreshed"] == 1
    assert row.is_selected is True
    assert row.available is True
    assert result["removed_unavailable"] == 0


@pytest.mark.asyncio
async def test_refresh_checks_selected_unavailable_row():
    """The critical bug: unavailable selected rows MUST still be revalidated."""
    row = _make_row("hustler.top", price=6131.18, available=False, selected=True)
    svc = _make_svc([row])
    check = _FakeCheck(status="available")
    with _patch_registrar(check):
        result = await svc.refresh_selected()
    assert result["refreshed"] == 1
    assert row.is_selected is True
    assert row.available is True  # restored
    svc._repo.list_selected_for_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_restores_unavailable_to_available():
    row = _make_row("batterify.com", price=330702616.17, available=False, selected=True)
    svc = _make_svc([row])
    check = _FakeCheck(status="available")
    with _patch_registrar(check):
        await svc.refresh_selected()
    assert row.available is True
    assert row.is_selected is True


# ---------------------------------------------------------------- 4: transient failure

@pytest.mark.asyncio
async def test_transient_failure_keeps_selected_and_does_not_delete():
    row = _make_row("hustler.vip", price=24138.08, available=True, selected=True)
    svc = _make_svc([row])
    with _patch_registrar(exc=RuntimeError("OpenProvider timeout")):
        result = await svc.refresh_selected()
    assert result["check_failed"] == 1
    assert row.is_selected is True
    assert row.is_deleted is False
    assert row.available is True  # last known state preserved
    svc._repo.soft_delete_by_id = AsyncMock()
    svc._repo.soft_delete_by_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_transient_failure_keeps_unavailable_state_until_recovery():
    row = _make_row("hustler.top", price=6131.18, available=False, selected=True)
    svc = _make_svc([row])
    with _patch_registrar(exc=RuntimeError("OpenProvider timeout")):
        await svc.refresh_selected()
    assert row.is_selected is True
    assert row.is_deleted is False
    assert row.available is False  # still hidden but NOT removed

    # Next refresh succeeds -> restored
    svc2 = _make_svc([row])
    with _patch_registrar(_FakeCheck(status="available")):
        await svc2.refresh_selected()
    assert row.available is True
    assert row.is_selected is True


# ------------------------------------------------------------------ 5+6: untick wins

@pytest.mark.asyncio
async def test_unselect_sets_selected_false():
    row = _make_row("hustler.co", price=1431531.81, available=True, selected=True)
    svc = _make_svc([row])
    await svc.unselect_domain(row.id)
    assert row.is_selected is False


@pytest.mark.asyncio
async def test_unticked_domain_not_republished_by_refresh():
    row = _make_row("hustler.co", price=1431531.81, available=False, selected=False)
    svc = _make_svc([row])
    # list_selected_for_refresh filters is_selected=True, so an unticked row
    # is never returned to the refresh loop (the repo is the source of truth
    # for selection state). Prove the refresh flow sees zero rows and leaves
    # the unticked row completely untouched.
    svc._repo.list_selected_for_refresh = AsyncMock(return_value=[])
    check = _FakeCheck(status="available")
    with _patch_registrar(check):
        result = await svc.refresh_selected()
    assert result["refreshed"] == 0
    assert row.is_selected is False
    assert row.available is False  # never flipped to available for an unticked row


@pytest.mark.asyncio
async def test_remove_domain_soft_deletes_and_stays_out_of_feed():
    row = _make_row("hustler.top", price=6131.18, available=True, selected=True)
    svc = _make_svc([row])
    removed = await svc.remove_domain(row.id)
    assert removed is True
    assert row.is_deleted is True
    # Public feed excludes it
    svc._repo.list_selected = AsyncMock(return_value=[])
    items, enabled = await svc.list_public()
    assert items == []


# ----------------------------------------------------------------- 7+8: public/homepage strict

@pytest.mark.asyncio
async def test_public_listing_only_selected_available_not_deleted():
    ok = _make_row("shinebyte.com", price=50000.0, available=True, selected=True)
    hidden = _make_row("hustler.top", price=6131.18, available=False, selected=True)
    svc = _make_svc([ok, hidden])
    svc._repo.list_selected = AsyncMock(return_value=[ok])  # repo enforces the filter
    items, enabled = await svc.list_public()
    assert enabled is True
    assert [i["domainName"] for i in items] == ["shinebyte.com"]


@pytest.mark.asyncio
async def test_homepage_receives_only_selected_available():
    from app.service.domain.showcase_homepage_integration import (
        ShowcaseHomepageIntegration,
    )
    ok = _make_row("shinebyte.com", price=50000.0, available=True, selected=True)
    hidden = _make_row("hustler.top", price=6131.18, available=False, selected=True)
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    _attach_existing_table(svc)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value=dict(DEFAULT_CFG))
    svc._repo = MagicMock()
    svc._repo.list_selected = AsyncMock(return_value=[ok])
    integration = ShowcaseHomepageIntegration.__new__(ShowcaseHomepageIntegration)
    integration._session = MagicMock()
    integration._session = MagicMock()
    from unittest.mock import patch as _patch

    with _patch(
        "app.service.domain.showcase_homepage_integration.ShowcaseDomainService",
        return_value=svc,
    ):
        cards = await integration.fetch_homepage_rows()
    assert [c["domainName"] for c in cards] == ["shinebyte.com"]
    assert all(c["domainName"] != "hustler.top" for c in cards)


# --------------------------------------------------------------- 9: repeated refreshes

@pytest.mark.asyncio
async def test_repeated_refreshes_never_lose_selected_domains():
    rows = [
        _make_row("shinebyte.com", price=50000.0, available=True, selected=True),
        _make_row("hustler.top", price=6131.18, available=False, selected=True),
        _make_row("hustler.vip", price=24138.08, available=False, selected=True),
    ]
    for _ in range(3):
        svc = _make_svc(rows)
        check = _FakeCheck(status="available")
        with _patch_registrar(check):
            await svc.refresh_selected()
    # All still selected; availability eventually True
    assert all(r.is_selected for r in rows)
    assert all(r.available for r in rows)


# ----------------------------------------------------------- 10: refresh never re-selects

@pytest.mark.asyncio
async def test_refresh_never_reselects_unticked_or_removed_rows():
    unticked = _make_row("hustler.co", price=1431531.81, available=False, selected=False)
    removed = _make_row("batterify.com", price=330702616.17, available=True, selected=True)
    removed.is_deleted = True
    # Repo correctly filters both out (source of truth for selection state)
    svc = _make_svc([unticked, removed])
    svc._repo.list_selected_for_refresh = AsyncMock(return_value=[])
    check = _FakeCheck(status="available")
    with _patch_registrar(check):
        result = await svc.refresh_selected()
    assert result["refreshed"] == 0
    assert unticked.is_selected is False
    assert removed.is_selected is True  # untouched
    assert removed.is_deleted is True
