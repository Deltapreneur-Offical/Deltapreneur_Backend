"""Showcase candidate generation tests (Phase 2) — mocks only, no DB, no network.

Covers the pure selection pipeline, candidate row construction, the
generation-lock guard, and the happy path end-to-end with a mocked
OpenProvider ``_check_tld_batches``.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AppException

# Import every ORM entity module (same walk the parent conftest performs) so
# SQLAlchemy mappers resolve (e.g. DomainListing -> ContactInfo) WITHOUT any
# database connection. Pure-mock tests never touch a database.
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


@pytest.fixture(autouse=True)
def _clear_showcase_scan_cache():
    """Module-level scan cache persists across tests — reset it each time."""
    from app.service.domain import showcase_domain_service

    showcase_domain_service._SHOWCASE_SCAN_CACHE.clear()
    yield
    showcase_domain_service._SHOWCASE_SCAN_CACHE.clear()


@pytest.fixture(autouse=True)
def _no_aftermarket_scan(monkeypatch):
    """Generate now also attempts an Afternic/Sedo scan for registry-taken
    extensions. Existing tests mock only the registry batch — default the
    aftermarket scan to empty so no provider call is attempted."""
    from app.service.domain import showcase_domain_service

    monkeypatch.setattr(
        showcase_domain_service,
        "_aftermarket_scan_for_label",
        AsyncMock(return_value=[]),
    )


@pytest.fixture(autouse=True)
def _cancel_never(monkeypatch):
    async def _no(_self, _status_id):
        return False

    monkeypatch.setattr(ShowcaseDomainService, "_cancel_requested", _no)

DEFAULT_CFG = {
    "enabled": False,
    "seed_labels": ["shinebyte", "solara"],
    "allowed_tlds": ["com", "ai", "io", "co"],
    "max_selected": 50,
    "refresh_interval_hours": 6,
    "last_refresh_at": None,
    "generation_lock": False,
}

RAW_FREE_PREMIUM = [
    {
        "domain": "shinebyte.com",
        "name": "shinebyte",
        "extension": "com",
        "status": "free",
        "is_premium": True,
        "price": {"reseller": {"price": 50000.0, "currency": "INR"}},
    }
]

RAW_TAKEN_PREMIUM = [
    {
        "domain": "takenpremium.com",
        "name": "takenpremium",
        "extension": "com",
        "status": "active",
        "is_premium": True,
        "price": {"reseller": {"price": 40000.0, "currency": "INR"}},
    }
]


def _item(fqdn: str, *, available: bool = True, premium: bool = True, price: float = 100.0):
    name, _, tld = fqdn.partition(".")
    return {
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


# ------------------------------------------------------------- pure selection

def test_select_candidates_filters_premium_available_and_tld():
    items = [
        _item("good.com", premium=True, available=True),
        _item("nopremium.com", premium=False, available=True),
        _item("taken.io", premium=True, available=False),
        _item("wrongtld.ai", premium=True, available=True),
    ]
    picked = ShowcaseDomainService._select_candidates(
        items,
        allowed_tlds=["com", "co"],
        excluded_fqdns=set(),
        count=50,
    )
    domains = [it["domain"] for it in picked]
    assert domains == ["good.com"]


def test_select_candidates_excludes_marketplace_fqdns():
    items = [_item("listed.com"), _item("free.com")]
    picked = ShowcaseDomainService._select_candidates(
        items,
        allowed_tlds=["com"],
        excluded_fqdns={"listed.com"},
        count=50,
    )
    assert [it["domain"] for it in picked] == ["free.com"]


def test_select_candidates_requires_positive_price():
    items = [_item("zeroprice.com", price=0.0), _item("good.com", price=100.0)]
    picked = ShowcaseDomainService._select_candidates(
        items,
        allowed_tlds=["com"],
        excluded_fqdns=set(),
        count=50,
    )
    assert [it["domain"] for it in picked] == ["good.com"]


def test_select_candidates_sorts_by_price_and_caps_count():
    items = [
        _item("expensive.com", price=900.0),
        _item("cheap.com", price=100.0),
        _item("mid.com", price=500.0),
    ]
    picked = ShowcaseDomainService._select_candidates(
        items,
        allowed_tlds=["com"],
        excluded_fqdns=set(),
        count=2,
    )
    assert [it["domain"] for it in picked] == ["cheap.com", "mid.com"]


# ------------------------------------------------------------- row building

def test_make_row_snapshots_and_never_publishes():
    row = ShowcaseDomainService._make_row("shinebyte", _item("shinebyte.com", price=50000.0))
    assert row.domain_name == "shinebyte.com"
    assert row.tld == "com"
    assert row.is_premium is True
    assert row.source == "registry"
    assert row.is_selected is False
    assert row.available is True
    assert row.create_price_inr == 50000.0
    assert row.payable_inr is not None
    assert row.payable_inr >= row.create_price_inr  # GST-inclusive payable
    assert row.price_snapshot_json is not None
    assert row.label == "shinebyte"


# ------------------------------------------------------- generation lock

async def test_generate_candidates_busy_lock_raises():
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    _attach_existing_table(svc)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value=DEFAULT_CFG)
    svc._config.claim_generation_lock = AsyncMock(return_value=False)

    with pytest.raises(AppException) as exc:
        await svc.generate_candidates(seed_labels=["shinebyte"])
    assert exc.value.status_code == 409
    assert exc.value.code == "SHOWCASE_GENERATION_BUSY"


# ------------------------------------------------------------ happy path

# ------------------------------------------- read-only guard (no-table DB)

def _svc_with_missing_table():
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    svc._session = MagicMock()
    svc._session.execute = AsyncMock(
        return_value=MagicMock(scalar=MagicMock(return_value=None))
    )
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value=DEFAULT_CFG)
    svc._config.claim_generation_lock = AsyncMock(return_value=True)
    svc._config.release_generation_lock = AsyncMock()
    return svc


def _attach_existing_table(svc) -> None:
    """Make table_available() return True (table exists) for write-path tests."""
    svc._session = MagicMock()
    svc._session.execute = AsyncMock(
        return_value=MagicMock(
            scalar=MagicMock(return_value="openprovider_showcase_domains")
        )
    )


async def test_generate_blocked_when_table_missing():
    svc = _svc_with_missing_table()
    with pytest.raises(AppException) as exc:
        await svc.generate_candidates(seed_labels=["shinebyte"])
    assert exc.value.status_code == 503
    assert exc.value.code == "SHOWCASE_MIGRATION_REQUIRED"
    svc._config.claim_generation_lock.assert_not_awaited()


async def test_select_unselect_remove_refresh_blocked_when_table_missing():
    from uuid import uuid4

    for method in ("select_domain", "unselect_domain", "remove_domain", "refresh_selected"):
        svc = _svc_with_missing_table()
        with pytest.raises(AppException) as exc:
            if method == "refresh_selected":
                await getattr(svc, method)()
            else:
                await getattr(svc, method)(uuid4())
        assert exc.value.status_code == 503, method
        assert exc.value.code == "SHOWCASE_MIGRATION_REQUIRED", method


async def test_list_public_empty_when_table_missing():
    svc = _svc_with_missing_table()
    items, enabled = await svc.list_public()
    assert items == []
    assert enabled is False


async def test_read_only_env_blocks_writes_even_when_table_exists(monkeypatch):
    monkeypatch.setenv("SHOWCASE_READ_ONLY", "1")
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    _attach_existing_table(svc)  # table EXISTS — mode must still block
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value=DEFAULT_CFG)
    with pytest.raises(AppException) as exc:
        await svc.generate_candidates(seed_labels=["shinebyte"])
    assert exc.value.status_code == 503
    assert exc.value.code == "SHOWCASE_READ_ONLY"
    # Config writes are covered by the same guard in the controller path.
    assert svc.read_only_mode() is True


# ----------------------------------------- ₹5L managed gate (Phase 6)

def test_showcase_metadata_above_5l_routes_to_managed_gate():
    from app.service.domain.managed_acquisition_pricing import (
        is_openprovider_managed_registration,
    )

    # Same metadata shape the frontend cart helper sends for showcase domains.
    # Gate is payable-based (price + 18% GST > 5L): 490k unit -> ~578k payable.
    above = {"domainName": "lux.com", "price": 600000.0, "isPremium": True, "tld": "com"}
    unit_below_but_crosses = {"domainName": "mid.com", "price": 490000.0, "isPremium": True, "tld": "com"}
    below = {"domainName": "shinebyte.com", "price": 400000.0, "isPremium": True, "tld": "com"}
    assert is_openprovider_managed_registration(above) is True
    assert is_openprovider_managed_registration(unit_below_but_crosses) is True
    assert is_openprovider_managed_registration(below) is False


def test_managed_gate_is_payable_based_not_unit_based():
    from app.service.domain.managed_acquisition_pricing import (
        is_managed_acquisition_payable,
    )

    # Unit price below 5L can still cross the gate once GST is added.
    assert is_managed_acquisition_payable(470000.0) is True
    assert is_managed_acquisition_payable(400000.0) is False


# ------------------------------------------------------- public feed (Phase 4)

def test_to_public_dict_never_leaks_internal_data():
    row = ShowcaseDomainService._make_row("shinebyte", _item("shinebyte.com", price=50000.0))
    public = ShowcaseDomainService.to_public_dict(row)
    assert public["source"] == "openprovider_showcase"
    assert public["domainName"] == "shinebyte.com"
    assert public["extension"] == ".com"
    assert public["isPremium"] is True
    assert public["priceInr"] == 50000.0
    assert public["managedAcquisition"] is False
    # No internal/provider/commission fields leak.
    assert "price_snapshot_json" not in public
    assert "providerUnitPriceInr" not in public
    assert "commissionRate" not in public
    assert "label" not in public


def test_to_public_dict_flags_managed_acquisition_over_5l():
    row = ShowcaseDomainService._make_row("lux", _item("lux.com", price=600000.0))
    public = ShowcaseDomainService.to_public_dict(row)
    assert public["managedAcquisition"] is True


async def test_list_public_returns_empty_when_disabled():
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value={**DEFAULT_CFG, "enabled": False})
    items, enabled = await svc.list_public()
    assert enabled is False
    assert items == []


async def test_list_public_returns_only_selected_when_enabled():
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    _attach_existing_table(svc)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value={**DEFAULT_CFG, "enabled": True})
    svc._repo = MagicMock()
    svc._repo.list_selected = AsyncMock(
        return_value=[ShowcaseDomainService._make_row("shinebyte", _item("shinebyte.com", price=50000.0))]
    )
    items, enabled = await svc.list_public()
    assert enabled is True
    assert len(items) == 1
    assert items[0]["source"] == "openprovider_showcase"


# ------------------------------------------------ background refresh (Phase 5)

def _now_iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


async def test_generate_candidates_early_exits_after_target():
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    _attach_existing_table(svc)
    svc._session.commit = AsyncMock()
    svc._repo = MagicMock()
    svc._repo.get_by_domain_name = AsyncMock(return_value=None)
    svc._repo.upsert_by_domain_name = AsyncMock(side_effect=lambda row: row)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value=DEFAULT_CFG)
    svc._config.claim_generation_lock = AsyncMock(return_value=True)
    svc._config.release_generation_lock = AsyncMock()
    svc._config.update = AsyncMock()
    svc._active_marketplace_fqdns = AsyncMock(return_value=set())
    svc.count_all = AsyncMock(return_value=2)

    with patch(
        "app.integrations.openprovider.client._check_tld_batches",
        new=AsyncMock(side_effect=[RAW_FREE_PREMIUM, []]),
    ) as mock_check:
        result = await svc.generate_candidates(
            seed_labels=["shinebyte", "secondlabel"], count=1
        )

    # Target reached on the first label -> second label is never scanned.
    assert mock_check.await_count == 1
    assert result["candidates_added"] == 1


async def test_refresh_if_due_skips_when_disabled():
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value={**DEFAULT_CFG, "enabled": False})
    svc.refresh_selected = AsyncMock()
    result = await svc.refresh_if_due()
    assert result["skipped"] is True
    assert result["reason"] == "disabled"
    svc.refresh_selected.assert_not_awaited()


async def test_refresh_if_due_skips_when_not_due():
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(
        return_value={**DEFAULT_CFG, "enabled": True, "last_refresh_at": _now_iso(0.5)}
    )
    svc.refresh_selected = AsyncMock()
    result = await svc.refresh_if_due()
    assert result["skipped"] is True
    assert result["reason"] == "not_due"
    svc.refresh_selected.assert_not_awaited()


async def test_refresh_if_due_runs_and_replenishes_below_max():
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(
        return_value={**DEFAULT_CFG, "enabled": True, "last_refresh_at": _now_iso(8)}
    )
    svc.refresh_selected = AsyncMock(return_value={"refreshed": 40, "removed_unavailable": 2})
    svc.count_selected = AsyncMock(side_effect=[40, 43])
    svc.generate_candidates = AsyncMock(return_value={"candidates_added": 3})

    result = await svc.refresh_if_due()

    assert result["skipped"] is False
    assert result["refresh"]["refreshed"] == 40
    assert result["replenished_candidates"] == 3
    # max_selected=50, selected=40 -> shortfall 10 passed to generation.
    assert svc.generate_candidates.await_args.kwargs["count"] == 10


async def test_generate_candidates_happy_path_persists_unselected():
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    _attach_existing_table(svc)
    svc._session.commit = AsyncMock()
    svc._repo = MagicMock()
    svc._repo.get_by_domain_name = AsyncMock(return_value=None)
    svc._repo.upsert_by_domain_name = AsyncMock(
        side_effect=lambda row: row
    )
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value=DEFAULT_CFG)
    svc._config.claim_generation_lock = AsyncMock(return_value=True)
    svc._config.release_generation_lock = AsyncMock()
    svc._config.update = AsyncMock()
    svc._active_marketplace_fqdns = AsyncMock(return_value=set())
    svc.count_all = AsyncMock(return_value=3)

    with patch(
        "app.integrations.openprovider.client._check_tld_batches",
        new=AsyncMock(return_value=RAW_FREE_PREMIUM + RAW_TAKEN_PREMIUM),
    ) as mock_check:
        result = await svc.generate_candidates(seed_labels=["shinebyte"], count=50)

    assert mock_check.await_count == 1
    assert result["labels_scanned"] == 1
    assert result["candidates_added"] == 1
    assert result["published"] == 0

    assert svc._repo.upsert_by_domain_name.await_count == 1
    created = svc._repo.upsert_by_domain_name.await_args.args[0]
    assert created.domain_name == "shinebyte.com"
    assert created.is_selected is False
    assert created.source == "registry"
    assert created.tld == "com"
    svc._config.release_generation_lock.assert_awaited_once()


async def test_claim_generation_lock_scoped_to_showcase_key():
    """Regression: the OR clause must stay grouped INSIDE the AND.

    Without the outer parens, ``AND`` binds tighter than ``OR`` and the WHERE
    matches every row whose JSON lacks a 'generation_lock' key — so jsonb_set
    runs on unrelated scalar rows ("cannot set path in scalar"). The fixed
    statement can ONLY ever target setting_key='showcase_config'.
    """
    from types import SimpleNamespace

    from sqlalchemy.dialects import postgresql

    from app.service.domain.showcase_config_service import (
        KEY_SHOWCASE_CONFIG,
        ShowcaseConfigService,
    )

    session = AsyncMock()
    svc = ShowcaseConfigService(session)
    svc._repo.insert_if_absent = AsyncMock()
    # Fast-path read: no stored config yet -> None -> proceeds to the atomic
    # guarded UPDATE.
    svc._repo.get = AsyncMock(return_value=None)
    captured: dict = {}

    async def fake_execute(stmt):
        captured["stmt"] = stmt
        return SimpleNamespace(rowcount=1)

    session.execute = AsyncMock(side_effect=fake_execute)

    assert await svc.claim_generation_lock() is True
    svc._repo.insert_if_absent.assert_awaited_once()

    sql = str(captured["stmt"].compile(dialect=postgresql.dialect()))
    assert (
        "WHERE platform_settings.setting_key = %(setting_key_1)s" in sql
    ), "lock must filter on the showcase_config key"
    assert (
        "AND ((setting_value::jsonb->>'generation_lock')::boolean = false "
        "OR setting_value::jsonb->>'generation_lock' IS NULL)" in sql
    ), "OR must stay grouped inside the AND (no all-row match)"
    assert "= false OR setting_value::jsonb->>'generation_lock' IS NULL) WHERE" not in sql


async def test_release_generation_lock_commits():
    """Regression: the lock release must be COMMITTED, otherwise it is
    rolled back on session close and the lock stays stuck (false 409s)."""
    from app.service.domain.showcase_config_service import ShowcaseConfigService

    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    svc = ShowcaseConfigService(session)

    await svc.release_generation_lock()

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


async def test_claim_generation_lock_missing_row_returns_false():
    """When the guarded UPDATE matches 0 rows (concurrent winner), claim=False."""
    from types import SimpleNamespace

    from app.service.domain.showcase_config_service import ShowcaseConfigService

    session = AsyncMock()
    svc = ShowcaseConfigService(session)
    svc._repo.insert_if_absent = AsyncMock()
    svc._repo.get = AsyncMock(return_value=None)
    session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=0))

    assert await svc.claim_generation_lock() is False


async def test_claim_generation_lock_fast_path_visible_lock():
    """Fast-path: when a running generation has COMMITTED its claim, a
    concurrent claim must return False immediately without issuing the
    guarded UPDATE (no 80s row-lock block, instant 409)."""
    from app.service.domain.showcase_config_service import ShowcaseConfigService

    session = AsyncMock()
    svc = ShowcaseConfigService(session)
    svc._repo.insert_if_absent = AsyncMock()
    svc._repo.get = AsyncMock(
        return_value='{"generation_lock": true, "enabled": false}'
    )
    session.execute = AsyncMock()

    assert await svc.claim_generation_lock() is False
    session.execute.assert_not_awaited()


async def test_generate_candidates_empty_body_lists_use_config():
    """Empty seed_labels/allowed_tlds in the body fall back to saved config,
    so a fresh Generate (before any Settings save) still works and never
    triggers OP calls for an empty label set."""
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    _attach_existing_table(svc)
    svc._session.commit = AsyncMock()
    svc._repo = MagicMock()
    svc._repo.get_by_domain_name = AsyncMock(return_value=None)
    svc._repo.upsert_by_domain_name = AsyncMock(side_effect=lambda row: row)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value=DEFAULT_CFG)  # seed_labels: shinebyte, solara
    svc._config.claim_generation_lock = AsyncMock(return_value=True)
    svc._config.release_generation_lock = AsyncMock()
    svc._config.update = AsyncMock()
    svc._active_marketplace_fqdns = AsyncMock(return_value=set())
    svc.count_all = AsyncMock(return_value=1)

    with patch(
        "app.integrations.openprovider.client._check_tld_batches",
        new=AsyncMock(return_value=RAW_FREE_PREMIUM + RAW_TAKEN_PREMIUM),
    ) as mock_check:
        result = await svc.generate_candidates(
            seed_labels=[], allowed_tlds=[], count=5
        )

    assert result["labels_scanned"] >= 1, "used config labels, not the empty body lists"
    assert mock_check.await_count >= 1
    assert result["published"] == 0


# ------------------------------------------------------- random generation

def test_generate_random_labels_unique_and_bounded():
    from app.constants.showcase_labels import generate_random_labels

    labels = generate_random_labels(50, seed=123)
    assert len(labels) == 50
    assert len(set(labels)) == 50
    assert all(
        l == "".join(c for c in l if c.isalnum()) and len(l) >= 4 for l in labels
    )
    # Deterministic with the same seed (tests), no duplicates within a run.
    assert generate_random_labels(20, seed=7) == generate_random_labels(20, seed=7)


def test_classify_items_reports_reasons():
    items = [
        _item("good.com"),
        _item("taken.io", available=False),
        _item("nopremium.com", premium=False),
        _item("wrongtld.co", premium=True, available=True),
        _item("listed.com"),
        _item("zeroprice.com", price=0.0),
    ]
    picked, reasons = ShowcaseDomainService._classify_items(
        items,
        allowed_tlds=["com"],
        excluded_fqdns={"listed.com"},
        count=50,
    )
    assert [it["domain"] for it in picked] == ["good.com"]
    assert reasons["taken"] == 1
    assert reasons["not_premium"] == 1
    assert reasons["tld_excluded"] == 1
    assert reasons["marketplace_listed"] == 1
    assert reasons["no_price"] == 1


def _random_check_response(labels, *, premium=True, available=True, tlds=("com",)):
    """Raw OP check response shaped like the live API, for any label names."""
    out = []
    for lab in labels:
        for tld in tlds:
            out.append(
                {
                    "domain": f"{lab}.{tld}",
                    "name": lab,
                    "extension": tld,
                    "status": "free" if available else "active",
                    "is_premium": premium,
                    "price": {"reseller": {"price": 50000.0, "currency": "INR"}},
                }
            )
    return out


def _random_svc():
    from app.service.domain.showcase_domain_service import ShowcaseDomainService

    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    _attach_existing_table(svc)
    svc._session.commit = AsyncMock()
    svc._repo = MagicMock()
    svc._repo.get_by_domain_name = AsyncMock(return_value=None)
    svc._repo.upsert_by_domain_name = AsyncMock(side_effect=lambda row: row)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value=DEFAULT_CFG)
    svc._config.claim_generation_lock = AsyncMock(return_value=True)
    svc._config.release_generation_lock = AsyncMock()
    svc._config.update = AsyncMock()
    svc._config.is_cancel_requested = AsyncMock(return_value=False)
    svc._active_marketplace_fqdns = AsyncMock(return_value=set())
    svc.count_all = AsyncMock(return_value=1)
    svc._scan_catalog_for_label = AsyncMock(return_value=[])
    return svc


async def test_generate_random_candidates_happy_path(monkeypatch):
    from app.service.domain import showcase_domain_service as sds

    monkeypatch.setattr(sds, "LABEL_PACING_SEC", 0.0)
    svc = _random_svc()

    async def fake_check(labels, tlds, **kwargs):
        return _random_check_response(labels, tlds=tuple(tlds))

    with patch(
        "app.integrations.openprovider.client._check_labels_batch",
        new=AsyncMock(side_effect=fake_check),
    ) as mock_check:
        result = await svc.generate_random_candidates(count=50, seed=1)

    assert mock_check.await_count >= 1
    assert result["mode"] == "random"
    assert result["generation_id"]
    assert result["candidates_added"] >= 1
    assert result["published"] == 0
    assert result["labels_planned"] <= 300
    # Never auto-publishes.
    assert all(
        call.args[0].is_selected is False
        for call in svc._repo.upsert_by_domain_name.await_args_list
    )
    # Status lifecycle: running -> complete and retrievable.
    status = sds.get_generation_status(result["generation_id"])
    assert status is not None
    assert status["state"] == "complete"
    assert status["candidatesFound"] == result["candidates_added"]
    assert status["targetCount"] == 50
    assert status["mode"] == "random"


async def test_generate_random_candidates_no_duplicates_across_runs(monkeypatch):
    from app.service.domain import showcase_domain_service as sds

    monkeypatch.setattr(sds, "LABEL_PACING_SEC", 0.0)
    monkeypatch.setattr(sds, "MAX_RANDOM_LABELS_PER_RUN", 7)
    svc = _random_svc()
    # Every candidate name already exists in the showcase pool (a prior run).
    svc._repo.get_by_domain_name = AsyncMock(return_value=MagicMock())

    async def fake_check(labels, tlds, **kwargs):
        return _random_check_response(labels, tlds=tuple(tlds))

    with patch(
        "app.integrations.openprovider.client._check_labels_batch",
        new=AsyncMock(side_effect=fake_check),
    ):
        result = await svc.generate_random_candidates(count=10, seed=2)

    assert result["candidates_added"] == 0
    assert result["skipped_existing"] >= 1
    svc._repo.upsert_by_domain_name.assert_not_awaited()


async def test_generate_random_candidates_shortfall_reports_reasons(monkeypatch):
    from app.service.domain import showcase_domain_service as sds

    monkeypatch.setattr(sds, "LABEL_PACING_SEC", 0.0)
    monkeypatch.setattr(sds, "MAX_RANDOM_LABELS_PER_RUN", 14)
    svc = _random_svc()

    async def fake_check(labels, tlds, **kwargs):
        # Everything comes back but NONE is premium -> nothing publishable.
        return _random_check_response(labels, premium=False, tlds=tuple(tlds))

    with patch(
        "app.integrations.openprovider.client._check_labels_batch",
        new=AsyncMock(side_effect=fake_check),
    ):
        result = await svc.generate_random_candidates(count=50, seed=3)

    assert result["candidates_added"] == 0
    assert result["shortfall"] is True
    assert "did not return enough" in result["message"]
    assert result["reasons"]["not_premium"] >= 1


async def test_generate_random_candidates_respects_tld_filter(monkeypatch):
    from app.service.domain import showcase_domain_service as sds

    monkeypatch.setattr(sds, "LABEL_PACING_SEC", 0.0)
    monkeypatch.setattr(sds, "MAX_RANDOM_LABELS_PER_RUN", 7)
    svc = _random_svc()

    async def fake_check(labels, tlds, **kwargs):
        return _random_check_response(labels, tlds=("com", "ai", "io", "co"))

    with patch(
        "app.integrations.openprovider.client._check_labels_batch",
        new=AsyncMock(side_effect=fake_check),
    ):
        result = await svc.generate_random_candidates(allowed_tlds=["ai"], count=10, seed=4)

    assert result["candidates_added"] >= 1
    assert result["reasons"]["tld_excluded"] >= 1
    for call in svc._repo.upsert_by_domain_name.await_args_list:
        assert call.args[0].tld == "ai"


async def test_generate_random_expands_com_only_tld_filter(monkeypatch):
    """Suggest names with .com-only must check popular extensions, not just .com."""
    from app.service.domain import showcase_domain_service as sds

    monkeypatch.setattr(sds, "LABEL_PACING_SEC", 0.0)
    monkeypatch.setattr(sds, "MAX_RANDOM_LABELS_PER_RUN", 7)
    svc = _random_svc()
    seen_tlds: list[list[str]] = []

    async def fake_check(labels, tlds, **kwargs):
        seen_tlds.append(list(tlds))
        return _random_check_response(labels, tlds=tuple(tlds))

    with patch(
        "app.integrations.openprovider.client._check_labels_batch",
        new=AsyncMock(side_effect=fake_check),
    ):
        result = await svc.generate_random_candidates(allowed_tlds=["com"], count=10, seed=4)

    assert result["candidates_added"] >= 1
    assert seen_tlds
    assert "io" in seen_tlds[0] or "ai" in seen_tlds[0]


async def test_generate_random_scans_saved_keywords_first(monkeypatch):
    from app.service.domain import showcase_domain_service as sds

    monkeypatch.setattr(sds, "LABEL_PACING_SEC", 0.0)
    monkeypatch.setattr(sds, "MAX_RANDOM_LABELS_PER_RUN", 7)
    svc = _random_svc()
    svc._scan_catalog_for_label = AsyncMock(return_value=list(RAW_FREE_PREMIUM))

    async def fake_check(labels, tlds, **kwargs):
        return _random_check_response(labels, premium=False, tlds=tuple(tlds))

    with patch(
        "app.integrations.openprovider.client._check_labels_batch",
        new=AsyncMock(side_effect=fake_check),
    ), patch.object(sds, "_enrich_renewal_prices", new=AsyncMock()):
        result = await svc.generate_random_candidates(count=5, seed=1)

    assert svc._scan_catalog_for_label.await_count >= 1
    assert result["candidates_added"] >= 1


def test_generate_random_labels_starts_with_dictionary_roots():
    from app.constants.showcase_labels import _ADJECTIVES, _NOUNS, generate_random_labels

    labels = generate_random_labels(30, seed=1)
    roots = {w for w in (*_ADJECTIVES, *_NOUNS) if len(w) >= 4}
    assert any(lab in roots for lab in labels[:30])


def test_is_narrow_premium_tld_list():
    from app.service.domain.showcase_domain_service import _is_narrow_premium_tld_list

    assert _is_narrow_premium_tld_list(["com"]) is True
    assert _is_narrow_premium_tld_list(["com", "net"]) is True
    assert _is_narrow_premium_tld_list(["com", "ai"]) is False
    assert _is_narrow_premium_tld_list([]) is False


# ------------------------------------------------------- full-catalog discovery

def _raw_premium_entry(fqdn: str, *, available: bool = True, price: float = 50000.0):
    name, _, tld = fqdn.partition(".")
    return {
        "domain": fqdn,
        "name": name,
        "extension": tld,
        "status": "free" if available else "active",
        "is_premium": True,
        "price": {"reseller": {"price": price, "currency": "INR"}},
    }


async def test_generate_candidates_discovers_across_catalog_when_no_tld_restriction(monkeypatch):
    """Empty allowed_tlds (the new default) must discover Premium domains on
    ANY TLD OpenProvider returns — e.g. hustler.shop/.fyi/.store — instead of
    being silently limited to com/ai/io/co."""
    from app.service.domain import showcase_domain_service as sds

    monkeypatch.setattr(sds, "LABEL_PACING_SEC", 0.0)
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    _attach_existing_table(svc)
    svc._session.commit = AsyncMock()
    svc._repo = MagicMock()
    svc._repo.get_by_domain_name = AsyncMock(return_value=None)
    svc._repo.upsert_by_domain_name = AsyncMock(side_effect=lambda row: row)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value={**DEFAULT_CFG, "allowed_tlds": []})
    svc._config.claim_generation_lock = AsyncMock(return_value=True)
    svc._config.release_generation_lock = AsyncMock()
    svc._config.update = AsyncMock()
    svc._active_marketplace_fqdns = AsyncMock(return_value=set())
    svc.count_all = AsyncMock(return_value=3)

    first_page = [
        _raw_premium_entry("hustler.shop", price=75000.0),
        _raw_premium_entry("hustler.fyi", price=1900.0),
        _raw_premium_entry("hustler.com", available=False),
    ]
    remaining_page = [
        _raw_premium_entry("hustler.store", price=125000.0),
        _raw_premium_entry("hustler.tech", available=False),
    ]

    with patch(
        "app.integrations.openprovider.client.search_domains_label_first_page",
        new=AsyncMock(return_value=(first_page, True, "token")),
    ) as mock_first, patch(
        "app.integrations.openprovider.client.search_domains_label_remaining",
        new=AsyncMock(side_effect=[(remaining_page, False, "token"), ([], False, None)]),
    ) as mock_rem:
        result = await svc.generate_candidates(
            seed_labels=["hustler"], allowed_tlds=[], count=10
        )

    assert mock_first.await_count == 1
    assert mock_rem.await_count == 1
    assert result["candidates_added"] == 3
    # The discovered TLDs are NOT rejected by an artificial allow-list.
    assert result["reasons"]["tld_excluded"] == 0
    tlds = sorted({call.args[0].tld for call in svc._repo.upsert_by_domain_name.await_args_list})
    assert tlds == ["fyi", "shop", "store"]


async def test_generate_candidates_early_exit_skips_remaining_catalog(monkeypatch):
    """Early-exit: when the first page already contains enough qualifying
    Premium domains, the remaining-catalog windows must NOT be scanned.

    Regression for the 150s scans: the old code always consumed every bounded
    window even after the first page had enough Premium candidates, which is
    what made keyword generation take ~2.5 minutes and left the admin staring
    at a silent spinner (and a second click -> 409).
    """
    from app.service.domain import showcase_domain_service as sds

    monkeypatch.setattr(sds, "LABEL_PACING_SEC", 0.0)
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    _attach_existing_table(svc)
    svc._session.commit = AsyncMock()
    svc._repo = MagicMock()
    svc._repo.get_by_domain_name = AsyncMock(return_value=None)
    svc._repo.upsert_by_domain_name = AsyncMock(side_effect=lambda row: row)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value={**DEFAULT_CFG, "allowed_tlds": []})
    svc._config.claim_generation_lock = AsyncMock(return_value=True)
    svc._config.release_generation_lock = AsyncMock()
    svc._config.update = AsyncMock()
    svc._active_marketplace_fqdns = AsyncMock(return_value=set())
    svc.count_all = AsyncMock(return_value=1)

    first_page = [
        _raw_premium_entry("hustler.shop", price=75000.0),
        _raw_premium_entry("hustler.fyi", price=1900.0),
    ]
    with patch(
        "app.integrations.openprovider.client.search_domains_label_first_page",
        new=AsyncMock(return_value=(first_page, True, "token")),
    ) as mock_first, patch(
        "app.integrations.openprovider.client.search_domains_label_remaining",
        new=AsyncMock(return_value=([], False, None)),
    ) as mock_rem:
        result = await svc.generate_candidates(
            seed_labels=["hustler"], allowed_tlds=[], count=1
        )

    # target=1 -> need=2 qualifying entries; the first page already has 2
    # (shop + fyi), so the remaining-catalog scan never runs.
    assert mock_first.await_count == 1
    assert mock_rem.await_count == 0
    assert result["candidates_added"] == 1  # cheapest qualifying (fyi)
    assert result["shortfall"] is False


async def test_generate_candidates_explicit_tlds_still_respected():
    """A non-empty allowed_tlds list must keep restricting the scan (legacy
    behavior) — full-catalog discovery only applies when it is empty."""
    svc = ShowcaseDomainService.__new__(ShowcaseDomainService)
    _attach_existing_table(svc)
    svc._session.commit = AsyncMock()
    svc._repo = MagicMock()
    svc._repo.get_by_domain_name = AsyncMock(return_value=None)
    svc._repo.upsert_by_domain_name = AsyncMock(side_effect=lambda row: row)
    svc._config = MagicMock()
    svc._config.get = AsyncMock(return_value=DEFAULT_CFG)
    svc._config.claim_generation_lock = AsyncMock(return_value=True)
    svc._config.release_generation_lock = AsyncMock()
    svc._config.update = AsyncMock()
    svc._active_marketplace_fqdns = AsyncMock(return_value=set())
    svc.count_all = AsyncMock(return_value=1)

    raw = [_raw_premium_entry("shinebyte.com"), _raw_premium_entry("shinebyte.shop")]
    with patch(
        "app.integrations.openprovider.client._check_tld_batches",
        new=AsyncMock(return_value=raw),
    ) as mock_check, patch(
        "app.integrations.openprovider.client.search_domains_label_first_page",
        new=AsyncMock(return_value=([], False, None)),
    ) as mock_first:
        result = await svc.generate_candidates(
            seed_labels=["shinebyte"], allowed_tlds=["com"], count=5
        )

    # Explicit list -> bounded _check_tld_batches path, discovery never runs.
    assert mock_check.await_count == 1
    assert mock_first.await_count == 0
    tlds = sorted({call.args[0].tld for call in svc._repo.upsert_by_domain_name.await_args_list})
    assert tlds == ["com"]
    assert result["candidates_added"] == 1


async def test_config_update_accepts_empty_allowed_tlds():
    """Empty allowed_tlds is the new default (no TLD restriction) and must be
    persistable through the config service."""
    from app.service.domain.showcase_config_service import ShowcaseConfigService

    session = AsyncMock()
    svc = ShowcaseConfigService(session)
    svc._repo.get = AsyncMock(return_value='{"allowed_tlds": ["com"]}')
    svc._repo.set = AsyncMock(return_value=MagicMock())
    session.commit = AsyncMock()

    updated = await svc.update({"allowed_tlds": []})
    assert updated["allowed_tlds"] == []
    svc._repo.set.assert_awaited_once()


async def test_config_default_allowed_tlds_empty():
    """The code default is empty (full-catalog discovery), not com/ai/io/co."""
    from app.service.domain.showcase_config_service import DEFAULT_SHOWCASE_CONFIG

    assert DEFAULT_SHOWCASE_CONFIG["allowed_tlds"] == []


async def test_generate_random_uses_curated_scope_when_no_tld_restriction(monkeypatch):
    """Random mode with empty allowed_tlds uses the popular first-wave TLD list."""
    from app.service.domain import showcase_domain_service as sds

    monkeypatch.setattr(sds, "LABEL_PACING_SEC", 0.0)
    monkeypatch.setattr(sds, "MAX_RANDOM_LABELS_PER_RUN", 7)
    svc = _random_svc()
    svc._config.get = AsyncMock(return_value={**DEFAULT_CFG, "allowed_tlds": []})

    async def fake_check(labels, tlds, **kwargs):
        return _random_check_response(labels, tlds=tuple(tlds))

    with patch(
        "app.integrations.openprovider.client._check_labels_batch",
        new=AsyncMock(side_effect=fake_check),
    ) as mock_check:
        result = await svc.generate_random_candidates(count=10, seed=5)

    assert result["candidates_added"] >= 1
    called_tlds = set()
    for call in mock_check.await_args_list:
        called_tlds.update(call.args[1])
    assert {"com", "io", "ai"} <= called_tlds


# ------------------------------------------------------- renewal enrichment

async def test_enrich_renewal_prices_fetches_registry_only(monkeypatch):
    """Renewal enrichment (GetPrice renew) fills registry-premium candidates
    and skips aftermarket (Afternic/Sedo) rows — so Showcase cards show the
    same "Renews at ₹X/yr" as storefront search results."""
    from app.service.domain import showcase_domain_service as sds

    registry_item = {
        "domain": "hustler.vip",
        "name": "hustler",
        "tld": ".vip",
        "available": True,
        "isPremium": True,
        "registrationPrice": 24138.08,
        "renewalPrice": None,
    }
    aftermarket_item = {
        "domain": "batterify.com",
        "name": "batterify",
        "tld": ".com",
        "available": True,
        "isPremium": True,
        "registrationPrice": 330702616.17,
        "renewalPrice": None,
        "_premium_provider": "afternic",
    }
    standard_item = {
        "domain": "plain.com",
        "name": "plain",
        "tld": ".com",
        "available": True,
        "isPremium": False,
        "renewalPrice": None,
    }

    async def fake_get_price(name, tld, operation=None, period=None):
        return {"price": {"reseller": {"price": 3005.99, "currency": "INR"}}}

    with patch(
        "app.integrations.openprovider.client.get_domain_price",
        new=AsyncMock(side_effect=fake_get_price),
    ):
        await sds._enrich_renewal_prices(
            [registry_item, aftermarket_item, standard_item]
        )

    # All available rows without renewal price get enriched.
    assert registry_item["renewalPrice"] == 3005.99
    assert aftermarket_item["renewalPrice"] == 3005.99
    assert standard_item["renewalPrice"] == 3005.99
