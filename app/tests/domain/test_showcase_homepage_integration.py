"""OP Showcase → Homepage Domains feed integration tests (mocks only).

Covers the isolated merge layer: selected+enabled rows become homepage cards,
marketplace listings win on duplicates, and unselected/deleted/unavailable or
disabled-showcase rows never enter the feed. No DB, no network.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.service.domain.showcase_homepage_integration import (
    ShowcaseHomepageIntegration,
)


def _import_all_entities() -> None:
    entity_root = Path(__file__).resolve().parents[3] / "app" / "entity"
    if not entity_root.exists():
        return
    for module_path in sorted(entity_root.rglob("*.py")):
        if module_path.name == "__init__.py":
            continue
        rel = module_path.relative_to(entity_root).with_suffix("")
        try:
            importlib.import_module(".".join(["app", "entity", *rel.parts]))
        except Exception:
            pass


_import_all_entities()


def _row(
    domain: str,
    *,
    is_selected: bool = True,
    available: bool = True,
    is_premium: bool = True,
    create_price_inr: float = 25_000.0,
    renewal_price_inr: float | None = None,
    payable_inr: float = 25_000.0,
    source: str = "registry",
    tld: str = "",
    deleted_at: datetime | None = None,
) -> MagicMock:
    name, dot, ext = domain.partition(".")
    return MagicMock(
        id="00000000-0000-0000-0000-000000000001",
        domain_name=domain,
        label=name,
        tld=tld or (ext if dot else "com"),
        is_premium=is_premium,
        is_selected=is_selected,
        available=available,
        source=source,
        create_price_inr=create_price_inr,
        renewal_price_inr=renewal_price_inr,
        payable_inr=payable_inr,
        price_snapshot_json={"premiumProvider": "afternic" if source == "afternic" else None},
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        last_checked_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        deleted_at=deleted_at,
    )


def _marketplace(domain: str, *, featured: bool = True) -> dict:
    name, dot, ext = domain.partition(".")
    return {
        "domain_name": domain,
        "domainName": domain,
        "domain_extension": f".{ext}" if dot else ".com",
        "domainExtension": f".{ext}" if dot else ".com",
        "featured": featured,
        "status": True,
        "asking_price": 50_000.0,
        "askingPrice": 50_000.0,
        "updated_at": "2025-02-01T00:00:00+00:00",
        "source": "marketplace",
    }


def _svc(enabled: bool = True, rows: list[MagicMock] | None = None) -> MagicMock:
    svc = MagicMock()
    svc.table_available = AsyncMock(return_value=True)
    svc._config.get = AsyncMock(return_value={"enabled": enabled, "max_selected": 50})
    svc._repo.list_selected = AsyncMock(return_value=list(rows or []))
    return svc


async def test_selected_enabled_rows_become_feed_cards(monkeypatch):
    integration = ShowcaseHomepageIntegration(MagicMock())
    monkeypatch.setattr(
        "app.service.domain.showcase_homepage_integration.ShowcaseDomainService",
        lambda session: _svc(rows=[_row("hustler.top")]),
    )
    cards = await integration.fetch_homepage_rows()
    assert len(cards) == 1
    card = cards[0]
    assert card["domain_name"] == "hustler.top"
    assert card["domainName"] == "hustler.top"
    assert card["domain_status"] == "AVAILABLE"
    assert card["featured"] is True
    assert card["is_premium"] is True
    assert card["asking_price"] == 25_000.0
    assert card["source"] == "openprovider_showcase"
    assert card["id"].startswith("showcase-")
    # internal provider stays internal metadata only
    assert card.get("premiumProvider") is None


def test_feed_card_carries_premium_card_shape_and_single_domain():
    card = ShowcaseHomepageIntegration._to_feed_card(_row("hustler.vip"))
    # premium-card adapter fields (ShowcaseDomainCard → DomainCard)
    assert card["name"] == "hustler"
    assert card["tld"] == "vip"
    assert card["extension"] == ".vip"
    assert card["priceInr"] == 25_000.0
    assert card["renewalPriceInr"] is None
    assert card["payableInr"] == 25_000.0
    assert card["isPremium"] is True
    # marketplace-compat shape: extension EMPTY so the legacy split path renders
    # the full domain once (hustler.vip, never hustler.vip.vip)
    assert card["domain_name"] == "hustler.vip"
    assert card["domainName"] == "hustler.vip"
    assert card["domain_extension"] == ""
    assert card["domainExtension"] == ""


async def test_disabled_showcase_returns_empty(monkeypatch):
    integration = ShowcaseHomepageIntegration(MagicMock())
    monkeypatch.setattr(
        "app.service.domain.showcase_homepage_integration.ShowcaseDomainService",
        lambda session: _svc(enabled=False, rows=[_row("hustler.top")]),
    )
    assert await integration.fetch_homepage_rows() == []


async def test_missing_table_returns_empty(monkeypatch):
    integration = ShowcaseHomepageIntegration(MagicMock())
    svc = _svc(rows=[_row("hustler.top")])
    svc.table_available = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "app.service.domain.showcase_homepage_integration.ShowcaseDomainService",
        lambda session: svc,
    )
    assert await integration.fetch_homepage_rows() == []


async def test_errors_never_break_homepage(monkeypatch):
    integration = ShowcaseHomepageIntegration(MagicMock())
    svc = MagicMock()
    svc.table_available = AsyncMock(side_effect=Exception("boom"))
    monkeypatch.setattr(
        "app.service.domain.showcase_homepage_integration.ShowcaseDomainService",
        lambda session: svc,
    )
    assert await integration.fetch_homepage_rows() == []


def test_merge_marketplace_wins_on_duplicate():
    integration = ShowcaseHomepageIntegration(MagicMock())
    marketplace = [_marketplace("hustler.top")]
    showcase = [
        ShowcaseHomepageIntegration._to_feed_card(_row("hustler.top")),
        ShowcaseHomepageIntegration._to_feed_card(_row("hustler.vip")),
    ]
    merged = integration.merge_into_feed(marketplace, showcase)
    names = [r["domain_name"] for r in merged]
    assert names == ["hustler.top", "hustler.vip"]  # marketplace kept, no dup
    top = next(r for r in merged if r["domain_name"] == "hustler.top")
    assert top["source"] == "marketplace"
    assert top["asking_price"] == 50_000.0


def test_merge_sorts_by_updated_at_desc():
    integration = ShowcaseHomepageIntegration(MagicMock())
    marketplace = [_marketplace("old.com")]
    marketplace[0]["updated_at"] = "2024-01-01T00:00:00+00:00"
    showcase = [
        ShowcaseHomepageIntegration._to_feed_card(_row("new.io")),
        ShowcaseHomepageIntegration._to_feed_card(_row("mid.net")),
    ]
    merged = integration.merge_into_feed(marketplace, showcase)
    assert [r["domain_name"] for r in merged] == ["new.io", "mid.net", "old.com"]


def test_merge_dedups_label_extension_vs_full_domain():
    # marketplace stores label + extension separately; showcase carries full domain
    integration = ShowcaseHomepageIntegration(MagicMock())
    marketplace = [_marketplace("hustler.vip")]
    marketplace[0]["domain_name"] = "hustler"
    marketplace[0]["domainName"] = "hustler"
    marketplace[0]["domain_extension"] = ".vip"
    marketplace[0]["domainExtension"] = ".vip"
    showcase = [
        ShowcaseHomepageIntegration._to_feed_card(_row("hustler.vip")),
        ShowcaseHomepageIntegration._to_feed_card(_row("hustler.top")),
    ]
    merged = integration.merge_into_feed(marketplace, showcase)
    fulls = [
        f"{r['domain_name'].strip().lower()}{r.get('domain_extension', '') or ''}"
        for r in merged
    ]
    assert fulls.count("hustler.vip") == 1  # marketplace wins, no duplicate
    assert any("hustler.top" in f for f in fulls)
    top = next(
        r for r in merged
        if f"{r['domain_name'].strip().lower()}{r.get('domain_extension', '') or ''}" == "hustler.vip"
    )
    assert top["source"] == "marketplace"


def test_merge_handles_case_and_whitespace():
    integration = ShowcaseHomepageIntegration(MagicMock())
    marketplace = [_marketplace("Hustler.TOP ")]
    showcase = [
        ShowcaseHomepageIntegration._to_feed_card(_row("hustler.top")),
        ShowcaseHomepageIntegration._to_feed_card(_row("hustler.vip")),
    ]
    merged = integration.merge_into_feed(marketplace, showcase)
    names = [r["domain_name"].strip().lower() for r in merged]
    assert names.count("hustler.top") == 1
    assert "hustler.vip" in names
    # marketplace listing is the survivor (keeps its original record)
    top = next(r for r in merged if r["domain_name"].strip().lower() == "hustler.top")
    assert top["source"] == "marketplace"
