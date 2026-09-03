"""OpenProvider Premium Showcase — candidate generation (Phase 2).

Discovery is label-based (OpenProvider has no "list all premium domains" API):
each seed keyword is batch-checked across the allowed TLDs using the EXISTING
provider-safe machinery (``_check_tld_batches``: 30 TLDs/request, bounded
concurrency, retries with backoff, poison-batch isolation). Only registry
results that are available AND registry-premium AND priced AND not already
listed on the HubRegistrar marketplace are persisted as CANDIDATES with
``is_selected=False``. Nothing is ever auto-published; admin ticks decide
public visibility (Phase 4).

OpenProvider is only ever called here (generation/refresh) — never from the
admin list or the public feed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, or_, select, text

from app.core.exceptions import AppException
from app.entity.cobranding.domain_listing_entity import DomainListing
from app.entity.domain.openprovider_showcase_entity import OpenProviderShowcaseDomain
from app.repository.showcase_domain_repository import ShowcaseDomainRepository
from app.service.domain.showcase_config_service import ShowcaseConfigService
from app.utils.domain_gst import domain_price_breakdown

logger = logging.getLogger(__name__)

# Showcase-scoped scan cache (per label + TLD set) so repeated "Generate"
# runs are free within the TTL. Distinct from the premium-search cache.
SHOWCASE_SCAN_CACHE_TTL_SEC = 900.0  # 15 minutes
_SHOWCASE_SCAN_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}

# Pacing between label scans — a cheap global knob protecting OpenProvider
# from bursts while a full rebuild (~50-100 labels) runs in the background.
LABEL_PACING_SEC = 0.5
MAX_LABELS_PER_RUN = 100
MAX_GENERATE_COUNT = 100

# Random Premium mode: hard cap on auto-generated labels checked per run and
# the per-request pair budget (mirrors the OP client batch size) used to size
# multi-label batches so each request stays provider-friendly.
MAX_RANDOM_LABELS_PER_RUN = 200
_CHECK_PAIRS_PER_REQUEST = 30

# Full-catalog discovery (empty allowed_tlds = no TLD restriction). Keyword
# generation scans the curated priority TLDs first (fast first page), then the
# remaining live catalog in bounded windows until it is exhausted — the same
# safe machinery the storefront search uses, so a keyword like "hustler"
# discovers qualifying Premium domains on ANY TLD OpenProvider returns
# (.shop/.fyi/.store/...) instead of being silently limited to an allow-list.
_CATALOG_WINDOW_SIZE = 60
_CATALOG_MAX_WINDOWS = 10
# Random mode: bounded curated TLD scope when no restriction is configured
# (covers the popular gTLDs incl. shop/store/tech/site/club/fyi).
_RANDOM_DISCOVERY_TLD_COUNT = 26
# First Random wave uses a short TLD list so more labels fit in each 30-pair
# OpenProvider request. Remaining curated TLDs run only if still short of target.
_RANDOM_FIRST_WAVE_TLDS = ("com", "net", "org", "io", "ai", "co")
# .com/.net/.org alone almost never return registry-premium for invented
# labels. Suggest names widens this to the first-wave list so Find can
# actually hit Premium inventory (Search by name still honours the filter).
_NARROW_PREMIUM_TLDS = frozenset({"com", "net", "org"})


def _is_narrow_premium_tld_list(allowed: list[str]) -> bool:
    if not allowed:
        return False
    return all(t in _NARROW_PREMIUM_TLDS for t in allowed)

# Aftermarket (Afternic/Sedo) discovery: these are the only gTLDs the
# aftermarket providers operate on, and a registry-TAKEN domain is the only
# case where an aftermarket listing is relevant. Aftermarket candidates are
# ALWAYS managed acquisitions (> ₹5L) — they must never enter the normal
# registry-registration checkout (GetPrice cannot quote a registry-taken
# aftermarket domain).
_AFTERMARKET_TLDS = ("com", "net", "org", "io", "co")
_AFTERMARKET_SCAN_CONCURRENCY = 2

# ---------------------------------------------------------------------------
# In-process generation status (progress + rejection reasons for the admin UI)
#
# Keyed by generation id; written by generate/refresh, read by the admin
# status endpoint while the request is in flight (async server -> concurrent
# read is fine). Single-worker scoped; never stored in the DB.
# ---------------------------------------------------------------------------
_GENERATION_STATUSES: dict[str, dict[str, Any]] = {}

_REASON_KEYS = (
    "invalid",
    "taken",
    "not_premium",
    "tld_excluded",
    "marketplace_listed",
    "no_price",
    "below_managed_threshold",
)


def _empty_reasons() -> dict[str, int]:
    return {k: 0 for k in _REASON_KEYS}


def _entry_tld(entry: dict[str, Any]) -> str:
    """Extension of a raw check entry, normalized (no dot).

    OpenProvider's domains/check response sometimes omits ``extension`` (only
    ``domain`` + ``status`` are present), so fall back to parsing the FQDN.
    """
    ext = str(entry.get("extension") or "").lstrip(".").lower()
    if not ext:
        fqdn = str(entry.get("domain") or "")
        if "." in fqdn:
            ext = fqdn.split(".", 1)[1].lower()
    return ext


async def _aftermarket_scan_for_label(
    label: str, exts: list[str]
) -> list[dict[str, Any]]:
    """Afternic → Sedo premium check for the given extensions (bounded).

    Mirrors the existing premium-search ``_aftermarket_scan`` protections:
    bounded concurrency (semaphore 2), Afternic preferred over Sedo, and only
    results that are available AND premium are returned, carrying
    ``_premium_provider`` so the caller can persist the source. Never
    publishes — the caller decides.
    """
    from app.integrations.openprovider.client import (
        _check_domain_raw,
        extract_is_premium,
        is_free,
    )

    if not exts:
        return []
    sem = asyncio.Semaphore(_AFTERMARKET_SCAN_CONCURRENCY)

    async def _one(ext: str) -> dict[str, Any] | None:
        async with sem:
            for provider in ("afternic", "sedo"):
                try:
                    am = await _check_domain_raw(label, ext, provider=provider)
                except Exception as exc:
                    logger.debug(
                        "showcase.aftermarket %s.%s %s: %s",
                        label, ext, provider, exc,
                    )
                    continue
                if is_free(am) and extract_is_premium(am):
                    am = dict(am)
                    am.setdefault("name", label)
                    am.setdefault("extension", ext)
                    am.setdefault("domain", f"{label}.{ext}")
                    am["_premium_provider"] = provider
                    return am
            return None

    found = await asyncio.gather(*[_one(ext) for ext in exts])
    return [x for x in found if x]


def _status_id() -> str:
    return str(uuid.uuid4())


def get_generation_status(generation_id: str) -> Optional[dict[str, Any]]:
    """Latest progress snapshot for a generation (or None when unknown)."""
    return _GENERATION_STATUSES.get(generation_id)


def _start_status(
    status_id: str, mode: str, target_count: int, labels_planned: int
) -> None:
    _GENERATION_STATUSES[status_id] = {
        "generationId": status_id,
        "mode": mode,
        "state": "running",
        "targetCount": target_count,
        "labelsPlanned": labels_planned,
        "labelsScanned": 0,
        "candidatesFound": 0,
        "skippedExisting": 0,
        "phase": "Starting...",
        "messages": [],
        "reasons": _empty_reasons(),
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "finishedAt": None,
        "shortfall": False,
        "message": None,
    }


def _update_status(status_id: str, **patch: Any) -> None:
    entry = _GENERATION_STATUSES.get(status_id)
    if entry is None:
        return
    entry.update(patch)
    # Live elapsed always available (frontend shows "working for Xs").
    started = entry.get("startedAt")
    if started:
        try:
            started_dt = datetime.fromisoformat(started)
            entry["elapsedMs"] = int(
                (datetime.now(timezone.utc) - started_dt).total_seconds() * 1000
            )
        except (TypeError, ValueError):
            pass
    # Determinate progress is reported per-label (the unit of work known up
    # front). The catalog-window scan deliberately does NOT drive the bar
    # (total windows unknown, early-exit makes it a poor estimator) — it
    # reports phase + candidatesFound + elapsed instead, and the UI shows an
    # indeterminate bar while progressPct is None.
    if "labelsScanned" in patch or "labelsPlanned" in patch:
        planned = entry.get("labelsPlanned") or 0
        scanned = entry.get("labelsScanned") or 0
        entry["progressPct"] = (
            round(min(100.0, 100.0 * scanned / planned), 1) if planned else None
        )
    pct = entry.get("progressPct")
    elapsed = entry.get("elapsedMs") or 0
    if pct and 0 < pct < 100 and elapsed > 0:
        entry["etaSeconds"] = round((elapsed / 1000.0) * (100.0 - pct) / pct, 1)
    else:
        entry["etaSeconds"] = None


def request_cancel_in_memory(generation_id: str) -> None:
    """Mark cancel on this process immediately (Cancel may also persist to DB)."""
    gid = (generation_id or "").strip()
    if not gid:
        return
    entry = _GENERATION_STATUSES.get(gid)
    if entry is None:
        _GENERATION_STATUSES[gid] = {
            "generationId": gid,
            "state": "running",
            "cancelRequested": True,
            "phase": "Stopping…",
        }
        return
    entry["cancelRequested"] = True
    entry["phase"] = "Stopping…"


def _finish_status(
    status_id: str,
    *,
    failed: bool = False,
    cancelled: bool = False,
    message: str | None = None,
) -> None:
    entry = _GENERATION_STATUSES.get(status_id)
    if entry is None:
        return
    if cancelled:
        entry["state"] = "cancelled"
        entry["phase"] = "Stopped."
    elif failed:
        entry["state"] = "failed"
        entry["phase"] = "Generation failed."
    else:
        entry["state"] = "complete"
        entry["phase"] = "Generation complete."
    if message:
        entry["message"] = message
    entry["finishedAt"] = datetime.now(timezone.utc).isoformat()


async def _enrich_renewal_prices(items: list[dict[str, Any]]) -> None:
    """Fetch missing renewal prices for registry-premium candidates (GetPrice renew).

    Mirrors the storefront / premium-search enrichment so Showcase cards show the
    same "Renews at ₹X/yr" line as the reference Premium Domain cards. Aftermarket
    (Afternic/Sedo) rows are skipped — one-time acquisition, no registry renewal
    exists. Bounded concurrency protects OpenProvider exactly like the existing
    storefront renewal enrichment.
    """
    from app.integrations.openprovider.client import (
        get_domain_price,
        extract_getprice_renewal_details,
    )
    from app.service.currency.exchange_rate_service import convert_foreign_to_inr

    pending = [
        it for it in items
        if it.get("available")
        and it.get("renewalPrice") is None
        and it.get("domain")
    ]
    if not pending:
        return
    logger.info(
        "showcase.renewal_enrich: %d items need renewal price fetch",
        len(pending),
    )

    async def _fetch(item: dict[str, Any]) -> None:
        domain = item.get("domain") or "?"
        try:
            name = str(item.get("name") or "").strip()
            tld = str(item.get("tld") or "").lstrip(".")
            if not name or not tld:
                logger.warning("showcase.renewal_fetch skipped domain=%s: name=%r tld=%r", domain, name, tld)
                return
            # Try actual domain name first, then fall back to generic name for TLD-level pricing
            for attempt_name in (name, "mydomain"):
                ren_quote = await get_domain_price(attempt_name, tld, operation="renew", period=1)
                ren_unit, ren_curr = extract_getprice_renewal_details(ren_quote)
                logger.info(
                    "showcase.renewal_fetch domain=%s attempt=%s tld=%s ren_unit=%s ren_curr=%s",
                    domain, attempt_name, tld, ren_unit, ren_curr,
                )
                if ren_unit and ren_unit > 0:
                    if ren_curr and ren_curr.upper() != "INR":
                        conv = convert_foreign_to_inr(ren_unit, ren_curr.upper())
                        renewal_inr = round(float(conv["amountInr"]), 2)
                    else:
                        renewal_inr = round(float(ren_unit), 2)
                    item["renewalPrice"] = renewal_inr
                    logger.info("showcase.renewal_fetch OK domain=%s attempt=%s renewal_inr=%s", domain, attempt_name, renewal_inr)
                    return
            logger.warning("showcase.renewal_fetch no_price domain=%s (both attempts failed)", domain)
        except Exception as exc:
            logger.warning(
                "showcase.renewal_fetch failed domain=%s err=%s",
                domain, exc,
            )

    sem = asyncio.Semaphore(4)

    async def _limited(item: dict[str, Any]) -> None:
        async with sem:
            await _fetch(item)

    await asyncio.gather(*[_limited(it) for it in pending])


class ShowcaseDomainService:
    def __init__(self, session) -> None:
        self._session = session
        self._repo = ShowcaseDomainRepository(session)
        self._config = ShowcaseConfigService(session)

    async def _cancel_requested(self, status_id: str) -> bool:
        entry = _GENERATION_STATUSES.get(status_id) or {}
        if entry.get("cancelRequested"):
            return True
        return await self._config.is_cancel_requested(status_id)

    # -------------------------------------------------------- read-only guard

    @staticmethod
    def read_only_mode() -> bool:
        """Positive lock: SHOWCASE_READ_ONLY=1 blocks EVERY showcase write.

        Deterministic and independent of whether the showcase table happens to
        exist in the target database (the shared RDS instance already has an
        empty one created out-of-band). Local/verification sessions set this so
        the new feature can be previewed without ANY possibility of writing.
        """
        return os.getenv("SHOWCASE_READ_ONLY", "").strip().lower() in {"1", "true", "yes"}

    async def table_available(self) -> bool:
        """True only when the showcase table exists in THIS database (pure read)."""
        try:
            res = await self._session.execute(
                text("SELECT to_regclass('public.openprovider_showcase_domains')")
            )
            return res.scalar() is not None
        except Exception:
            return False

    async def ensure_table(self) -> None:
        """Raise before ANY showcase write."""
        if self.read_only_mode():
            raise AppException(
                "Showcase is in read-only preview mode for this session "
                "(SHOWCASE_READ_ONLY=1). No changes were made.",
                status_code=503,
                code="SHOWCASE_READ_ONLY",
            )
        if not await self.table_available():
            raise AppException(
                "Showcase is in read-only preview on this database: its table is "
                "not applied, so no changes were made. Nothing was written.",
                status_code=503,
                code="SHOWCASE_MIGRATION_REQUIRED",
            )

    # ------------------------------------------------------------ discovery

    async def _scan_catalog_for_label(
        self,
        label: str,
        allowed_tlds: list[str],
        *,
        status_id: Optional[str] = None,
        target: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Scan a label against OpenProvider and return raw check entries.

        * When ``allowed_tlds`` is non-empty (admin restriction): check exactly
          those TLDs (legacy bounded behavior).
        * When ``allowed_tlds`` is empty (new default): full-catalog discovery
          — priority TLDs first (fast first page, same as the storefront
          search), then bounded windows over the remaining live catalog.
          Discovery STOPS EARLY as soon as enough potentially-qualifying
          entries (available + premium) have been collected — it never scans
          the whole remaining catalog just to fill ``count`` when the first
          page already contains enough Premium domains. This is what lets a
          keyword like ``hustler`` find Premium domains on ANY TLD
          OpenProvider returns (.shop/.fyi/.store/.tech/.site/.club/...) in
          seconds instead of ~150s, without hammering OpenProvider.

        Uses the existing safe machinery only (bounded concurrency, retries,
        in-process cache, timeout) — no new OpenProvider endpoints, no
        uncontrolled loops. While scanning, live progress (phase, window
        counter, qualifying candidates found) is written to the generation
        status so the admin UI can stream it.
        """
        from app.integrations.openprovider.client import (
            is_free,
            search_domains_label_first_page,
            search_domains_label_remaining,
        )

        if allowed_tlds:
            from app.integrations.openprovider.client import _check_tld_batches

            return await _check_tld_batches(
                label, allowed_tlds, concurrency=4, max_retries=2
            )

        def _qualifying(entries: list[dict[str, Any]]) -> int:
            """Cheap raw pre-filter (available + premium + parseable TLD).

            Classification may still reject a few (already marketplace-listed,
            no price), so the caller uses a margin over the target.
            """
            return sum(
                1
                for e in entries
                if is_free(e) and e.get("is_premium") and _entry_tld(e)
            )

        need = max(1, int(target or 1) * 2)
        raw: list[dict[str, Any]] = []
        first_page, _more, _tok = await search_domains_label_first_page(label)
        raw.extend(first_page)
        if status_id:
            _update_status(
                status_id,
                phase=f"Checking {label} — scanning catalog…",
                candidatesFound=min(need, _qualifying(raw)),
            )
        if _qualifying(raw) >= need:
            if status_id:
                _update_status(
                    status_id,
                    phase=f"Checking {label} — enough Premium domains found",
                    candidatesFound=min(need, _qualifying(raw)),
                )
            return raw

        # Continue over the remaining catalog in bounded windows until we have
        # enough qualifying entries (early exit) or the safe scope is consumed
        # (or a provider failure stops us).
        offset = 0
        for w in range(1, _CATALOG_MAX_WINDOWS + 1):
            if status_id and await self._cancel_requested(status_id):
                break
            try:
                chunk, more, _tok = await search_domains_label_remaining(
                    label, offset=offset, chunk_size=_CATALOG_WINDOW_SIZE
                )
            except Exception as exc:
                logger.warning(
                    "showcase.scan.remaining_failed label=%s offset=%s err=%s",
                    label, offset, exc,
                )
                break
            if chunk:
                raw.extend(chunk)
            if status_id:
                _update_status(
                    status_id,
                    phase=f"Checking {label} — catalog window {w}/{_CATALOG_MAX_WINDOWS}…",
                    windowsScanned=w,
                    windowsTotal=_CATALOG_MAX_WINDOWS,
                    candidatesFound=min(need, _qualifying(raw)),
                )
            if _qualifying(raw) >= need:
                break
            offset += _CATALOG_WINDOW_SIZE
            if not more:
                break

        return raw

    # ------------------------------------------------------------ pure pipeline

    @staticmethod
    def _classify_items(
        items: list[dict[str, Any]],
        *,
        allowed_tlds: list[str],
        excluded_fqdns: set[str],
        count: int,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """Filter registry items to publishable candidates AND tally why the
        rest were rejected (pure, testable).

        Acceptance rules (identical to the former ``_select_candidates``):
        FQDN valid; available; registry premium; TLD in allow-list; not an
        active HubRegistrar marketplace listing; positive customer price.
        Sorted by price ascending, capped at ``count``. The second return
        value is the per-reason rejection count so the UI can explain a
        shortfall instead of showing a bare "0 candidates".
        """
        allowed = {str(t).lstrip(".").lower() for t in allowed_tlds}
        reasons = _empty_reasons()
        picked: list[dict[str, Any]] = []
        for it in items:
            fqdn = str(it.get("domain") or "").lower().strip()
            tld = str(it.get("tld") or "").lstrip(".").lower()
            if not fqdn or "." not in fqdn:
                reasons["invalid"] += 1
                continue
            if not it.get("available"):
                reasons["taken"] += 1
                continue
            if not it.get("isPremium"):
                reasons["not_premium"] += 1
                continue
            if allowed and tld not in allowed:
                reasons["tld_excluded"] += 1
                continue
            if fqdn in excluded_fqdns:
                reasons["marketplace_listed"] += 1
                continue
            try:
                price = float(it.get("registrationPrice") or 0)
            except (TypeError, ValueError):
                price = 0.0
            if price <= 0:
                reasons["no_price"] += 1
                continue
            # Aftermarket (Afternic/Sedo) candidates are always accepted
            # during discovery — the managed threshold applies only at
            # checkout, not at inventory-pool creation.
            picked.append(it)

        picked.sort(key=lambda x: float(x.get("registrationPrice") or 0))
        return picked[: max(1, int(count))], reasons

    @staticmethod
    def _select_candidates(
        items: list[dict[str, Any]],
        *,
        allowed_tlds: list[str],
        excluded_fqdns: set[str],
        count: int,
    ) -> list[dict[str, Any]]:
        """Compatibility wrapper around ``_classify_items`` (picked only)."""
        picked, _ = ShowcaseDomainService._classify_items(
            items,
            allowed_tlds=allowed_tlds,
            excluded_fqdns=excluded_fqdns,
            count=count,
        )
        return picked

    async def _persist_from_raw(
        self,
        *,
        label: str,
        raw: list[dict[str, Any]],
        tlds_in_scope: list[str],
        classify_allowed: list[str],
        excluded_fqdns: set[str],
        builder: Any,
        target: int,
        reason_totals: dict[str, int],
    ) -> tuple[int, int]:
        """Build, classify, and upsert unselected rows for one label.

        Never sets ``is_selected``. Returns (added, skipped_existing).
        """
        from app.integrations.openprovider.client import is_free

        items = builder._build_tld_items(raw, label)
        taken_exts = {
            ext for r in raw
            if not is_free(r) and (ext := _entry_tld(r))
        }
        aftermarket_scope = tlds_in_scope or list(_AFTERMARKET_TLDS)
        aftermarket_exts = [
            t for t in aftermarket_scope
            if t in _AFTERMARKET_TLDS and t in taken_exts
        ]
        if aftermarket_exts:
            try:
                am_raw = await _aftermarket_scan_for_label(label, aftermarket_exts)
            except Exception as exc:
                logger.warning(
                    "showcase.persist.aftermarket_failed label=%s err=%s",
                    label, exc,
                )
                am_raw = []
            if am_raw:
                provider_by_domain = {
                    str(e.get("domain") or "").lower(): e.get("_premium_provider")
                    for e in am_raw
                }
                am_items = builder._build_tld_items(am_raw, label)
                for it in am_items:
                    prov = provider_by_domain.get(str(it.get("domain") or "").lower())
                    if prov:
                        it["_premium_provider"] = prov
                items = items + am_items

        picked, reasons = self._classify_items(
            items,
            allowed_tlds=classify_allowed,
            excluded_fqdns=excluded_fqdns,
            count=target,
        )
        for k, v in reasons.items():
            reason_totals[k] += v
        await _enrich_renewal_prices(picked)
        added = 0
        skipped_existing = 0
        for item in picked:
            row = self._make_row(label, item)
            existing = await self._repo.get_by_domain_name(row.domain_name)
            if existing is not None:
                skipped_existing += 1
                continue
            await self._repo.upsert_by_domain_name(row)
            added += 1
        return added, skipped_existing

    @staticmethod
    def _make_row(label: str, item: dict[str, Any]) -> OpenProviderShowcaseDomain:
        """Build an unselected candidate row from a built TLD item."""
        fqdn = str(item.get("domain") or "").lower().strip()
        tld = str(item.get("tld") or "").lstrip(".").lower()
        # Aftermarket origin (Afternic/Sedo) is carried on the built item via
        # ``_premium_provider`` (correlated by FQDN from the raw aftermarket
        # scan) and persisted as the row ``source``.
        premium_provider = item.get("_premium_provider") or None
        source = (
            str(premium_provider).lower()
            if premium_provider in ("afternic", "sedo")
            else "registry"
        )
        price = 0.0
        try:
            price = float(item.get("registrationPrice") or 0)
        except (TypeError, ValueError):
            price = 0.0
        payable = None
        if price > 0:
            try:
                payable = float(domain_price_breakdown(price, years=1)["totalInr"])
            except Exception:
                logger.warning("showcase.payable.failed domain=%s price=%s", fqdn, price)

        renewal = None
        try:
            renewal = float(item["renewalPrice"]) if item.get("renewalPrice") else None
        except (TypeError, ValueError):
            renewal = None

        snapshot = {
            k: item.get(k)
            for k in (
                "registryTier",
                "currency",
                "providerUnitPriceInr",
                "minPeriodYears",
                "source",
            )
        }
        snapshot["premiumProvider"] = premium_provider

        return OpenProviderShowcaseDomain(
            id=uuid.uuid4(),
            domain_name=fqdn,
            label=(label or "").strip()[:64] or None,
            tld=tld or "unknown",
            is_premium=bool(item.get("isPremium")),
            source=source,
            create_price_inr=price or None,
            renewal_price_inr=renewal,
            payable_inr=payable,
            price_snapshot_json=snapshot,
            available=True,
            last_checked_at=datetime.now(timezone.utc),
            is_selected=False,
            display_order=0,
        )

    # ------------------------------------------------------------------- reads

    async def _active_marketplace_fqdns(self) -> set[str]:
        """FQDNs currently listed on the HubRegistrar marketplace (not deleted/taken down).

        Mirrors ``DomainListingRepository.find_active_by_name`` semantics. These
        domains must NEVER become showcase candidates — checkout routes
        marketplace-listed domains to the marketplace flow.
        """
        stmt = select(
            func.lower(DomainListing.domain_name),
            DomainListing.domain_extension,
        ).where(
            DomainListing.is_deleted.is_(False),
            DomainListing.taken_down.is_(False),
        )
        rows = (await self._session.execute(stmt)).all()
        out: set[str] = set()
        for name, ext in rows:
            if name and ext:
                out.add(f"{name}.{str(ext).lstrip('.')}".lower())
        return out

    async def count_all(self) -> int:
        stmt = (
            select(func.count())
            .select_from(OpenProviderShowcaseDomain)
            .where(
                or_(
                    OpenProviderShowcaseDomain.is_deleted.is_(False),
                    OpenProviderShowcaseDomain.is_deleted.is_(None),
                )
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def count_selected(self) -> int:
        stmt = (
            select(func.count())
            .select_from(OpenProviderShowcaseDomain)
            .where(
                OpenProviderShowcaseDomain.is_selected.is_(True),
                or_(
                    OpenProviderShowcaseDomain.is_deleted.is_(False),
                    OpenProviderShowcaseDomain.is_deleted.is_(None),
                ),
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    @staticmethod
    def to_dict(row: OpenProviderShowcaseDomain) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "domainName": row.domain_name,
            "label": row.label,
            "tld": row.tld,
            "isPremium": row.is_premium,
            "source": row.source,
            "createPriceInr": row.create_price_inr,
            "renewalPriceInr": row.renewal_price_inr,
            "payableInr": row.payable_inr,
            "available": row.available,
            "lastCheckedAt": row.last_checked_at.isoformat() if row.last_checked_at else None,
            "isSelected": row.is_selected,
            "displayOrder": row.display_order,
            "createdAt": row.created_at.isoformat() if row.created_at else None,
            "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
        }

    async def list_rows(
        self,
        *,
        filters: dict[str, Any] | None = None,
        sort: str | None = "newest",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await self._repo.list_rows(
            filters=filters,
            sort=sort,
            page=page,
            page_size=page_size,
        )
        return [self.to_dict(r) for r in rows], total

    @staticmethod
    def to_public_dict(row: OpenProviderShowcaseDomain) -> dict[str, Any]:
        """Marketplace-card-compatible public shape (NO internal data leaked)."""
        name, dot, ext = row.domain_name.partition(".")
        return {
            "source": "openprovider_showcase",
            "showcaseId": str(row.id),
            "domainName": row.domain_name,
            "name": name,
            "extension": f".{ext}" if dot and ext else f".{row.tld}",
            "isPremium": row.is_premium,
            "registryTier": "premium" if row.is_premium else "standard",
            "premiumProvider": (row.price_snapshot_json or {}).get("premiumProvider"),
            "askingPrice": row.create_price_inr,
            "priceInr": row.create_price_inr,
            "renewalPriceInr": row.renewal_price_inr,
            "payableInr": row.payable_inr,
            "managedAcquisition": bool(
                row.payable_inr and row.payable_inr > 500_000.0
            ),
            "available": row.available,
            "lastCheckedAt": row.last_checked_at.isoformat() if row.last_checked_at else None,
            "currency": (row.price_snapshot_json or {}).get("currency") or "INR",
        }

    async def list_public(self) -> tuple[list[dict[str, Any]], bool]:
        """Public showcase feed — only selected+available rows, only when enabled."""
        if not await self.table_available():
            return [], False
        cfg = await self._config.get()
        enabled = bool(cfg.get("enabled"))
        if not enabled:
            return [], False
        rows = await self._repo.list_selected()
        return [self.to_public_dict(r) for r in rows], True

    # ------------------------------------------------------- admin operations

    async def select_domain(self, row_id: uuid.UUID) -> dict[str, Any]:
        """Publish a candidate after a live revalidation (one-time OP check).

        Select-time checks (F7/F3): the domain must still be registrable via
        OpenProvider AND must not have become a marketplace listing. If it is
        taken, unpriceable, or marketplace-listed, it is NOT published.
        """
        await self.ensure_table()
        row = await self._repo.get_by_id(row_id)
        if row is None:
            raise AppException("Showcase domain not found.", status_code=404)

        cfg = await self._config.get()
        max_selected = int(cfg.get("max_selected") or 50)
        if not row.is_selected and await self.count_selected() >= max_selected:
            raise AppException(
                f"Maximum of {max_selected} selected showcase domains reached. "
                "Untick another domain first.",
                status_code=400,
                code="SHOWCASE_MAX_SELECTED",
            )

        from app.service.domain.domain_registration_service import DomainRegistrationService

        svc = DomainRegistrationService(self._session)
        is_aftermarket = row.source in ("afternic", "sedo")
        try:
            check = await svc.check_registration_domain(
                row.domain_name, include_aftermarket=is_aftermarket
            )
        except Exception as exc:
            logger.warning(
                "showcase.select.check_failed domain=%s err=%s", row.domain_name, exc,
            )
            raise AppException(
                "Could not verify availability with OpenProvider. Try again.",
                status_code=502,
            ) from exc

        if check.status != "available":
            row.available = False
            row.last_checked_at = datetime.now(timezone.utc)
            await self._repo.save(row)
            raise AppException(
                "This domain is no longer available for registration and was not published.",
                status_code=409,
                code="SHOWCASE_UNAVAILABLE",
            )

        if is_aftermarket:
            # Aftermarket (Afternic/Sedo) candidates are managed acquisitions:
            # the live aftermarket check price is authoritative (GetPrice would
            # quote the standard registry price for a registry-taken domain)
            # and the managed threshold is re-enforced so the domain can NEVER
            # be routed through the normal registry-registration checkout.
            try:
                unit_price = float(getattr(check, "unitPrice") or 0)
            except (TypeError, ValueError):
                unit_price = 0.0
            if unit_price <= 0:
                row.available = False
                row.last_checked_at = datetime.now(timezone.utc)
                await self._repo.save(row)
                raise AppException(
                    "Could not verify the aftermarket premium price. Not published.",
                    status_code=502,
                    code="SHOWCASE_AFTERMARKET_PRICE_FAILED",
                )
            payable = float(domain_price_breakdown(unit_price, years=1)["totalInr"])
            # Managed threshold removed — all aftermarket domains can be
            # published regardless of payable amount.
            row.create_price_inr = unit_price
            row.payable_inr = payable
            row.price_snapshot_json = {
                "registryTier": "premium",
                "currency": getattr(check, "priceCurrency") or "INR",
                "premiumProvider": row.source,
                "minPeriodYears": getattr(check, "minPeriodYears") or 1,
                "priceSource": getattr(check, "priceSource") or "aftermarket_check",
                "refreshedAtSelect": True,
            }
        else:
            # Refresh the price snapshot at selection time (one live quote).
            try:
                quote = await svc.quote_registration_period_price(
                    row.domain_name, 1, require_live_price=True
                )
                period_total = float(quote.get("price") or 0)
                if period_total > 0:
                    row.create_price_inr = period_total
                    row.payable_inr = float(
                        domain_price_breakdown(period_total, years=1)["totalInr"]
                    )
                    row.price_snapshot_json = {
                        "registryTier": quote.get("registryTier"),
                        "currency": quote.get("providerCurrency") or quote.get("currency"),
                        "providerUnitPriceInr": quote.get("providerUnitPriceInr"),
                        "minPeriodYears": quote.get("minPeriodYears"),
                        "priceSource": quote.get("priceSource"),
                        "refreshedAtSelect": True,
                    }
            except Exception as exc:
                logger.warning(
                    "showcase.select.quote_failed domain=%s err=%s", row.domain_name, exc,
                )

        row.available = True
        row.last_checked_at = datetime.now(timezone.utc)
        row.is_selected = True
        await self._repo.save(row)
        await self._session.commit()
        return self.to_dict(row)

    async def unselect_domain(self, row_id: uuid.UUID) -> dict[str, Any]:
        await self.ensure_table()
        row = await self._repo.get_by_id(row_id)
        if row is None:
            raise AppException("Showcase domain not found.", status_code=404)
        row.is_selected = False
        await self._repo.save(row)
        await self._session.commit()
        return self.to_dict(row)

    async def remove_domain(self, row_id: uuid.UUID) -> bool:
        await self.ensure_table()
        row = await self._repo.get_by_id(row_id)
        if row is None:
            raise AppException("Showcase domain not found.", status_code=404)
        await self._repo.soft_delete_by_id(row_id)
        await self._session.commit()
        return True

    async def refresh_selected(self) -> dict[str, Any]:
        """Revalidate EVERY selected domain live; never drop selected rows.

        State separation (Selected = admin intent, Available = live OP status):
        - Selected rows are NEVER unselected, soft-deleted, or removed by this
          method. Only the admin's explicit Untick/Remove can change selection.
        - Public visibility follows ``available`` only: hidden rows stay visible
          in the admin Selected/Active section with their current status.
        - Refresh iterates ``list_selected_for_refresh()`` — selected rows
          REGARDLESS of availability — so a temporarily unavailable domain is
          re-checked every refresh and automatically restored to
          ``available=True`` once OpenProvider confirms it again. The old bug
          (refresh only revalidated currently-available rows) permanently
          stranded hidden selected domains.
        - A transient provider/API failure (check threw) does NOT flip
          availability or delete anything: the row keeps its last known state
          and is re-checked next refresh (bounded by the scheduler cadence).
        - OP-confirmed unavailable / unpriceable rows are hidden
          (available=False) but stay selected for admin review.
        """
        await self.ensure_table()
        cfg = await self._config.get()
        if not await self._config.claim_generation_lock():
            raise AppException(
                "A showcase generation/refresh is already in progress. Try again shortly.",
                status_code=409,
                code="SHOWCASE_GENERATION_BUSY",
            )
        # Make the claim visible to other workers immediately so a concurrent
        # Generate/Refresh fails fast (409) instead of blocking on the row
        # lock until this generation finishes.
        await self._session.commit()
        try:
            from app.service.domain.domain_registration_service import DomainRegistrationService

            svc = DomainRegistrationService(self._session)
            # Selected + not-deleted rows REGARDLESS of availability — the fix.
            selected = await self._repo.list_selected_for_refresh()
            refreshed = 0
            unavailable = 0
            price_failed = 0
            check_failed = 0
            for row in selected:
                is_aftermarket = row.source in ("afternic", "sedo")
                try:
                    check = await svc.check_registration_domain(
                        row.domain_name, include_aftermarket=is_aftermarket
                    )
                except Exception as exc:
                    # Transient provider failure: never treat as confirmed
                    # unavailability. Keep selection + last known availability;
                    # the next refresh re-checks and can restore it.
                    logger.warning(
                        "showcase.refresh.check_failed domain=%s err=%s",
                        row.domain_name, exc,
                    )
                    row.last_checked_at = datetime.now(timezone.utc)
                    await self._repo.save(row)
                    check_failed += 1
                    continue

                if check.status != "available":
                    # OP definitively reports unavailable / marketplace-listed.
                    # Hide from the public feed but KEEP selected for admin
                    # review — never auto-remove an admin-approved domain.
                    row.available = False
                    row.last_checked_at = datetime.now(timezone.utc)
                    await self._repo.save(row)
                    unavailable += 1
                    continue

                if is_aftermarket:
                    # Aftermarket rows revalidate via the live aftermarket check
                    # (GetPrice would quote the standard registry price).
                    try:
                        unit_price = float(getattr(check, "unitPrice") or 0)
                    except (TypeError, ValueError):
                        unit_price = 0.0
                    if unit_price <= 0:
                        row.available = False
                        price_failed += 1
                    else:
                        row.create_price_inr = unit_price
                        row.payable_inr = float(
                            domain_price_breakdown(unit_price, years=1)["totalInr"]
                        )
                        row.available = True
                        refreshed += 1
                else:
                    try:
                        quote = await svc.quote_registration_period_price(
                            row.domain_name, 1, require_live_price=True
                        )
                        period_total = float(quote.get("price") or 0)
                        if period_total <= 0:
                            raise ValueError("non-positive live price")
                        row.create_price_inr = period_total
                        row.payable_inr = float(
                            domain_price_breakdown(period_total, years=1)["totalInr"]
                        )
                        row.available = True
                        refreshed += 1
                        # Use the renewal price already computed by check_registration_domain
                        # (which extracts from OP check response + GetPrice renew fallback).
                        if check.renewalPriceInr is not None:
                            row.renewal_price_inr = round(float(check.renewalPriceInr), 2)
                        elif row.renewal_price_inr is None:
                            # Third fallback: direct GetPrice renew for domains where
                            # check_registration_domain couldn't get renewal pricing
                            # (common for aftermarket/Afternic/Sedo domains).
                            try:
                                from app.integrations.openprovider.client import (
                                    get_domain_price as _gp_renew,
                                    extract_getprice_renewal_details as _egr,
                                )
                                from app.service.currency.exchange_rate_service import convert_foreign_to_inr as _cvt
                                _name_sld = row.domain_name.split(".")[0]
                                _ext_dot = "." + row.domain_name.split(".")[1] if "." in row.domain_name else ""
                                _ext_no = _ext_dot.lstrip(".")
                                _rq = await _gp_renew(_name_sld, _ext_no, operation="renew", period=1)
                                _ru, _rc = _egr(_rq)
                                if _ru and _ru > 0:
                                    _code = (_rc or "INR").upper()
                                    if _code != "INR":
                                        _conv = _cvt(_ru, _code)
                                        row.renewal_price_inr = round(float(_conv["amountInr"]), 2)
                                    else:
                                        row.renewal_price_inr = round(float(_ru), 2)
                                # If still None, try with a generic name to get TLD-level pricing
                                if row.renewal_price_inr is None:
                                    _rq2 = await _gp_renew("mydomain", _ext_no, operation="renew", period=1)
                                    _ru2, _rc2 = _egr(_rq2)
                                    if _ru2 and _ru2 > 0:
                                        _code2 = (_rc2 or "INR").upper()
                                        if _code2 != "INR":
                                            _conv2 = _cvt(_ru2, _code2)
                                            row.renewal_price_inr = round(float(_conv2["amountInr"]), 2)
                                        else:
                                            row.renewal_price_inr = round(float(_ru2), 2)
                            except Exception as _renew_exc:
                                logger.warning(
                                    "showcase.refresh.direct_renewal_fetch domain=%s err=%s",
                                    row.domain_name, _renew_exc,
                                )
                        # else: keep existing row.renewal_price_inr (already set)
                        logger.info(
                            "showcase.refresh.renewal domain=%s check_renewal_inr=%s final=%s",
                            row.domain_name,
                            check.renewalPriceInr,
                            row.renewal_price_inr,
                        )
                    except Exception as exc:
                        logger.warning(
                            "showcase.refresh.quote_failed domain=%s err=%s",
                            row.domain_name, exc,
                        )
                        row.available = False
                        price_failed += 1
                row.last_checked_at = datetime.now(timezone.utc)
                await self._repo.save(row)

            await self._config.update(
                {"last_refresh_at": datetime.now(timezone.utc).isoformat()}
            )
            await self._session.commit()
            return {
                "refreshed": refreshed,
                # Never auto-removed anymore; kept selected and hidden instead.
                "removed_unavailable": 0,
                "unavailable": unavailable,
                "hidden_price_failed": price_failed,
                "check_failed": check_failed,
                "selected_remaining": await self.count_selected(),
            }
        finally:
            try:
                await self._config.release_generation_lock()
            except Exception:
                logger.exception("showcase.refresh.lock_release_failed")

    # ------------------------------------------------------------ scheduler

    async def refresh_if_due(self) -> dict[str, Any]:
        """Background entry point: refresh when due, then replenish the pool.

        Honors ``refresh_interval_hours`` via ``last_refresh_at``. Refreshing
        revalidates SELECTED rows live (including currently-unavailable ones),
        restoring availability when OpenProvider confirms it; it NEVER unselects
        or soft-deletes a selected row. Replenish only re-scans seed labels to
        keep an UNSELECTED candidate pool near ``max_selected`` — it NEVER
        auto-publishes; only admin ticks select.
        The scheduler's advisory lock plus the showcase generation lock keep
        concurrent runs impossible, even across workers.
        """
        cfg = await self._config.get()
        if not bool(cfg.get("enabled")):
            return {"skipped": True, "reason": "disabled"}

        interval_hours = max(1, int(cfg.get("refresh_interval_hours") or 6))
        last_raw = cfg.get("last_refresh_at")
        now = datetime.now(timezone.utc)
        if last_raw:
            try:
                last_dt = datetime.fromisoformat(str(last_raw))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                if (now - last_dt).total_seconds() < interval_hours * 3600:
                    return {"skipped": True, "reason": "not_due"}
            except ValueError:
                pass  # unparseable -> treat as due

        refresh_result = await self.refresh_selected()

        # Replenish the UNSELECTED candidate pool (never auto-publishes).
        replenished = 0
        try:
            max_selected = max(1, int(cfg.get("max_selected") or 50))
            selected = await self.count_selected()
            if selected < max_selected:
                gen = await self.generate_candidates(count=max_selected - selected)
                replenished = int(gen.get("candidates_added") or 0)
        except AppException as exc:
            logger.warning("showcase.replenish.skipped %s", exc)
        except Exception:
            logger.exception("showcase.replenish.failed")

        return {
            "skipped": False,
            "refresh": refresh_result,
            "replenished_candidates": replenished,
            "selected": await self.count_selected(),
        }

    # -------------------------------------------------------------- generation

    async def generate_candidates(
        self,
        *,
        seed_labels: Optional[list[str]] = None,
        allowed_tlds: Optional[list[str]] = None,
        count: int = 50,
        generation_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Generate unselected candidates by scanning seed labels (registry only).

        Candidates are persisted with ``is_selected=False`` — NEVER
        auto-published. Respects the atomic cross-process generation lock and
        reports live progress (``get_generation_status``) plus per-reason
        rejection tallies so the UI can explain shortfalls.
        """
        cfg = await self._config.get()

        # An empty body list means "not provided" -> fall back to the saved
        # config so a fresh Generate (before any Settings save) still works.
        labels = [
            str(x).strip().lower()
            for x in (seed_labels or cfg.get("seed_labels") or [])
            if str(x).strip()
        ]
        labels = labels[:MAX_LABELS_PER_RUN]
        if not labels:
            raise AppException(
                "No seed labels configured. Add seed labels in showcase settings first.",
                status_code=400,
            )

        # NOTE: allowed_tlds=[] from the frontend means "no restriction"
        # (clear the extension limit). We must distinguish [] from None:
        # only fall back to the saved config when the parameter is None.
        _raw_tlds = allowed_tlds if allowed_tlds is not None else (cfg.get("allowed_tlds") or [])
        allowed = [
            str(t).lstrip(".").lower()
            for t in _raw_tlds
            if str(t).strip()
        ]
        # Empty allowed_tlds is the default = NO TLD restriction. Generation
        # then discovers qualifying Premium domains across the full OpenProvider
        # catalog (see ``_scan_catalog_for_label``) instead of raising.
        count = max(1, min(int(count), MAX_GENERATE_COUNT))
        target = count

        status_id = generation_id or _status_id()
        _start_status(status_id, "keyword", target, len(labels))
        _update_status(status_id, phase="Searching OpenProvider...")

        await self.ensure_table()
        if not await self._config.claim_generation_lock():
            _finish_status(
                status_id,
                failed=True,
                message="Another generation/refresh is already in progress.",
            )
            raise AppException(
                "A showcase generation/refresh is already in progress. Try again shortly.",
                status_code=409,
                code="SHOWCASE_GENERATION_BUSY",
            )
        await self._session.commit()

        try:
            from app.integrations.openprovider.client import is_free
            from app.service.domain.domain_registration_service import DomainRegistrationService

            builder = DomainRegistrationService(self._session)
            excluded = await self._active_marketplace_fqdns()

            labels_scanned = 0
            added_total = 0
            per_label: dict[str, int] = {}
            skipped_existing = 0
            reason_totals = _empty_reasons()
            cancelled = False

            for label in labels:
                if await self._cancel_requested(status_id):
                    cancelled = True
                    break



                cache_key = f"showcase_v1|{label}|{','.join(sorted(allowed)) or 'all'}"
                cached = _SHOWCASE_SCAN_CACHE.get(cache_key)
                if cached and (time.monotonic() - cached[0]) < SHOWCASE_SCAN_CACHE_TTL_SEC:
                    raw: list[dict[str, Any]] = cached[1]
                else:
                    try:
                        raw = await self._scan_catalog_for_label(
                            label,
                            allowed,
                            status_id=status_id,
                            target=target,
                        )
                    except Exception as exc:
                        logger.warning(
                            "showcase.generate.label_failed label=%s err=%s", label, exc,
                        )
                        _update_status(status_id, phase=f"OpenProvider error on {label} — skipped")
                        continue
                    _SHOWCASE_SCAN_CACHE[cache_key] = (time.monotonic(), raw)

                labels_scanned += 1
                items = builder._build_tld_items(raw, label)

                # Aftermarket (Afternic/Sedo) discovery for this label: only
                # registry-TAKEN extensions that the aftermarket providers
                # support. When no TLD restriction is configured, all supported
                # aftermarket gTLDs are in scope. The provider marker is
                # correlated back onto the built items (by FQDN) so _make_row
                # persists source="afternic"/"sedo".
                taken_exts = {
                    ext for r in raw
                    if not is_free(r) and (ext := _entry_tld(r))
                }
                aftermarket_scope = allowed or list(_AFTERMARKET_TLDS)
                aftermarket_exts = [
                    t for t in aftermarket_scope
                    if t in _AFTERMARKET_TLDS and t in taken_exts
                ]
                if aftermarket_exts:
                    try:
                        am_raw = await _aftermarket_scan_for_label(
                            label, aftermarket_exts
                        )
                    except Exception as exc:
                        logger.warning(
                            "showcase.generate.aftermarket_failed label=%s err=%s",
                            label, exc,
                        )
                        am_raw = []
                    if am_raw:
                        provider_by_domain = {
                            str(e.get("domain") or "").lower(): e.get("_premium_provider")
                            for e in am_raw
                        }
                        am_items = builder._build_tld_items(am_raw, label)
                        for it in am_items:
                            prov = provider_by_domain.get(
                                str(it.get("domain") or "").lower()
                            )
                            if prov:
                                it["_premium_provider"] = prov
                        items = items + am_items

                picked, reasons = self._classify_items(
                    items,
                    allowed_tlds=allowed,
                    excluded_fqdns=excluded,
                    count=target,
                )
                for k, v in reasons.items():
                    reason_totals[k] += v
                # Fetch missing renewal prices (registry-premium only) so cards
                # show "Renews at ₹X/yr" exactly like the storefront search.
                await _enrich_renewal_prices(picked)
                label_added = 0
                for item in picked:
                    row = self._make_row(label, item)
                    existing = await self._repo.get_by_domain_name(row.domain_name)
                    if existing is not None:
                        skipped_existing += 1
                        continue
                    await self._repo.upsert_by_domain_name(row)
                    label_added += 1
                added_total += label_added
                per_label[label] = per_label.get(label, 0) + label_added
                _update_status(
                    status_id,
                    labelsScanned=labels_scanned,
                    candidatesFound=added_total,
                    skippedExisting=skipped_existing,
                    reasons=reason_totals,
                    phase=f"Checking {label}...",
                )
                # Early exit once we have enough new candidates (bounds OP load
                # when the background job replenishes a small shortfall).
                if added_total >= target:
                    break
                await asyncio.sleep(LABEL_PACING_SEC)

            shortfall = added_total < target
            msg = None
            if cancelled:
                msg = (
                    f"Stopped. {added_total} candidate(s) kept in the inventory "
                    "pool (not published)."
                )
            elif shortfall:
                msg = (
                    f"{added_total} Premium domains found. OpenProvider did not "
                    f"return enough qualifying domains to reach {target}."
                )
            if not cancelled:
                await self._config.update({"last_refresh_at": datetime.now(timezone.utc).isoformat()})
            await self._session.commit()
            _finish_status(status_id, cancelled=cancelled, message=msg)

            return {
                "mode": "keyword",
                "generation_id": status_id,
                "cancelled": cancelled,
                "labels_scanned": labels_scanned,
                "labels_planned": len(labels),
                "candidates_added": added_total,
                "skipped_existing": skipped_existing,
                "reasons": reason_totals,
                "shortfall": shortfall and not cancelled,
                "message": msg,
                "per_label": per_label,
                "total_candidates": await self.count_all(),
                "published": 0,
                "note": "Candidates are unselected. Tick domains in admin to publish.",
            }
        finally:
            try:
                await self._config.release_generation_lock()
            except Exception:
                logger.exception("showcase.generate.lock_release_failed")

    async def generate_random_candidates(
        self,
        *,
        allowed_tlds: Optional[list[str]] = None,
        count: int = 50,
        seed: Optional[int] = None,
        generation_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Random Premium mode — no typed keyword required.

        Saved Keywords (seed labels) are catalog-scanned first — that is the
        path that actually finds registry-premium inventory. Remaining slots
        are filled by dictionary-root / invented-label batches. A .com-only
        (or .com/.net/.org-only) limit is widened to popular extensions;
        Search by name still honours a strict TLD filter. Never auto-publishes.
        """
        from app.constants.showcase_labels import generate_random_labels

        cfg = await self._config.get()
        # NOTE: allowed_tlds=[] from the frontend means "no restriction"
        # (clear the extension limit). We must distinguish [] from None:
        # only fall back to the saved config when the parameter is None.
        _raw_tlds = allowed_tlds if allowed_tlds is not None else (cfg.get("allowed_tlds") or [])
        allowed = [
            str(t).lstrip(".").lower()
            for t in _raw_tlds
            if str(t).strip()
        ]
        expanded_narrow = _is_narrow_premium_tld_list(allowed)
        # Empty allowed_tlds: short popular TLD wave so Random batches many
        # labels per OpenProvider request. A .com-only saved limit is widened
        # the same way — otherwise Suggest names returns 0 Premium hits.
        tlds_to_check = (
            list(_RANDOM_FIRST_WAVE_TLDS) if (not allowed or expanded_narrow) else allowed
        )
        classify_allowed = [] if expanded_narrow else allowed
        count = max(1, min(int(count), MAX_GENERATE_COUNT))
        target = count

        seed_labels = [
            str(x).strip().lower()
            for x in (cfg.get("seed_labels") or [])
            if str(x).strip()
        ][:MAX_LABELS_PER_RUN]

        labels = generate_random_labels(MAX_RANDOM_LABELS_PER_RUN, seed=seed)
        if not labels and not seed_labels:
            raise AppException(
                "Could not generate any candidate labels. Try again.",
                status_code=502,
            )

        status_id = generation_id or _status_id()
        _start_status(status_id, "random", target, len(seed_labels) + len(labels))
        _update_status(status_id, phase="Searching OpenProvider...")

        await self.ensure_table()
        if not await self._config.claim_generation_lock():
            _finish_status(
                status_id,
                failed=True,
                message="Another generation/refresh is already in progress.",
            )
            raise AppException(
                "A showcase generation/refresh is already in progress. Try again shortly.",
                status_code=409,
                code="SHOWCASE_GENERATION_BUSY",
            )
        await self._session.commit()

        try:
            from app.integrations.openprovider.client import _check_labels_batch
            from app.service.domain.domain_registration_service import DomainRegistrationService

            builder = DomainRegistrationService(self._session)
            excluded = await self._active_marketplace_fqdns()

            labels_scanned = 0
            added_total = 0
            skipped_existing = 0
            per_label: dict[str, int] = {}
            reason_totals = _empty_reasons()
            cancelled = False

            # Catalog-scan saved Keywords first (same discovery path as
            # Search by name). A .com-only limit uses the full catalog here.
            scan_allowed = [] if expanded_narrow else allowed
            for label in seed_labels:
                if await self._cancel_requested(status_id):
                    cancelled = True
                    break
                if added_total >= target:
                    break
                try:
                    seed_raw = await self._scan_catalog_for_label(
                        label,
                        scan_allowed,
                        status_id=status_id,
                        target=target,
                    )
                except Exception as exc:
                    logger.warning(
                        "showcase.random.seed_scan_failed label=%s err=%s",
                        label, exc,
                    )
                    _update_status(
                        status_id,
                        phase=f"OpenProvider error on {label} — skipped",
                    )
                    continue
                label_added, label_skipped = await self._persist_from_raw(
                    label=label,
                    raw=seed_raw,
                    tlds_in_scope=scan_allowed or list(_RANDOM_FIRST_WAVE_TLDS),
                    classify_allowed=classify_allowed,
                    excluded_fqdns=excluded,
                    builder=builder,
                    target=target,
                    reason_totals=reason_totals,
                )
                labels_scanned += 1
                added_total += label_added
                skipped_existing += label_skipped
                per_label[label] = label_added
                _update_status(
                    status_id,
                    labelsScanned=labels_scanned,
                    candidatesFound=added_total,
                    skippedExisting=skipped_existing,
                    reasons=reason_totals,
                    phase=f"Checking {label}...",
                )
                if added_total >= target:
                    break
                await asyncio.sleep(LABEL_PACING_SEC)

            # One request per chunk: keep the (label x tld) pair count at or
            # below the provider batch size so each chunk is ~1 request.
            chunk_size = max(1, min(_CHECK_PAIRS_PER_REQUEST // max(1, len(tlds_to_check)), 10))

            for start in range(0, len(labels), chunk_size):
                if added_total >= target:
                    break
                if await self._cancel_requested(status_id):
                    cancelled = True
                    break
                chunk = labels[start : start + chunk_size]
                try:
                    raw = await _check_labels_batch(
                        chunk,
                        tlds_to_check,
                        concurrency=2,
                        max_retries=2,
                    )
                except Exception as exc:
                    logger.warning(
                        "showcase.random.chunk_failed labels=%s err=%s", chunk, exc,
                    )
                    _update_status(
                        status_id,
                        phase=f"OpenProvider error on {chunk[0]}... — skipped",
                        message=f"OpenProvider error: {exc}",
                    )
                    continue

                by_label: dict[str, list[dict[str, Any]]] = {}
                for entry in raw:
                    name = str(entry.get("name") or "").strip().lower()
                    by_label.setdefault(name, []).append(entry)

                for label in chunk:
                    label_raw = by_label.get(label, [])
                    if label_raw:
                        cache_key = f"showcase_v1|{label}|{','.join(sorted(tlds_to_check))}"
                        _SHOWCASE_SCAN_CACHE[cache_key] = (time.monotonic(), label_raw)
                    label_added, label_skipped = await self._persist_from_raw(
                        label=label,
                        raw=label_raw,
                        tlds_in_scope=tlds_to_check,
                        classify_allowed=classify_allowed,
                        excluded_fqdns=excluded,
                        builder=builder,
                        target=target,
                        reason_totals=reason_totals,
                    )
                    labels_scanned += 1
                    added_total += label_added
                    skipped_existing += label_skipped
                    per_label[label] = label_added
                    _update_status(
                        status_id,
                        labelsScanned=labels_scanned,
                        candidatesFound=added_total,
                        skippedExisting=skipped_existing,
                        reasons=reason_totals,
                        phase=f"Checking {label}...",
                    )
                    if added_total >= target:
                        break
                if added_total >= target:
                    break
                await asyncio.sleep(LABEL_PACING_SEC)

            shortfall = added_total < target
            msg = None
            if cancelled:
                msg = (
                    f"Stopped. {added_total} candidate(s) kept in the inventory "
                    "pool (not published)."
                )
            elif shortfall:
                msg = (
                    f"{added_total} Premium domains found. OpenProvider did not "
                    f"return enough qualifying domains to reach {target}."
                )
                if added_total == 0:
                    msg += (
                        " Use Search by name with a real word (hustler, mint, nova) "
                        "and leave Limit extensions blank. Save those words as Keywords."
                    )
            if not cancelled:
                await self._config.update({"last_refresh_at": datetime.now(timezone.utc).isoformat()})
            await self._session.commit()
            _finish_status(status_id, cancelled=cancelled, message=msg)

            return {
                "mode": "random",
                "generation_id": status_id,
                "cancelled": cancelled,
                "labels_scanned": labels_scanned,
                "labels_planned": len(seed_labels) + len(labels),
                "candidates_added": added_total,
                "skipped_existing": skipped_existing,
                "reasons": reason_totals,
                "shortfall": shortfall and not cancelled,
                "message": msg,
                "per_label": per_label,
                "total_candidates": await self.count_all(),
                "published": 0,
                "note": "Candidates are unselected. Tick domains in admin to publish.",
            }
        finally:
            try:
                await self._config.release_generation_lock()
            except Exception:
                logger.exception("showcase.random.lock_release_failed")
