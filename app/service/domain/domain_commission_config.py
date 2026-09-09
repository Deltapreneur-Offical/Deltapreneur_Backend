"""Runtime-editable commission/markup config for domain services.

The canonical configuration is stored in the shared ``platform_settings``
database table.  A process-local snapshot keeps the existing synchronous
pricing helpers cheap; request dependencies refresh that snapshot from the
database before pricing is calculated.

Schema (all percentages stored as decimal, e.g. 3% → 0.03):
{
  "registration": { "default": 0.03, "by_tld": { ... } },
  "premium_registration": { "default": 0.03, "by_tld": { ... } },
  "renewal":     { "default": 0.03, "by_tld": {} },
  "transfer":    { "default": 0.03, "by_tld": {} },
  "email":       { "default": 0.0  },
  "ssl":         { "default": 0.0  },
  "dnssec":      { "default": 0.0  },
  "restore":     { "default": 0.0  },
  "easydmarc":   { "default": 0.0  },
  "spamexperts": { "default": 0.0  }
}
"""

from __future__ import annotations

import json
import logging
from hashlib import sha256
from copy import deepcopy
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repository.platform_settings_repository import PlatformSettingsRepository

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_CONFIG_FILE = _DATA_DIR / "domain_commission.json"
KEY_DOMAIN_COMMISSION_CONFIG = "domain_commission_config"


class CommissionService:
    """Canonical commission service keys (JSON snake_case values)."""

    REGISTRATION = "registration"
    PREMIUM_REGISTRATION = "premium_registration"
    RENEWAL = "renewal"
    TRANSFER = "transfer"
    EMAIL = "email"
    SSL = "ssl"
    DNSSEC = "dnssec"
    RESTORE = "restore"
    EASYDMARC = "easydmarc"
    SPAMEXPERTS = "spamexperts"

    ALL = (
        REGISTRATION,
        PREMIUM_REGISTRATION,
        RENEWAL,
        TRANSFER,
        EMAIL,
        SSL,
        DNSSEC,
        RESTORE,
        EASYDMARC,
        SPAMEXPERTS,
    )
    WITH_TLD = (REGISTRATION, PREMIUM_REGISTRATION, RENEWAL, TRANSFER)


_DEFAULTS: dict[str, Any] = {
    CommissionService.REGISTRATION: {"default": 0.03, "by_tld": {}},
    CommissionService.PREMIUM_REGISTRATION: {"default": 0.03, "by_tld": {}},
    CommissionService.RENEWAL: {"default": 0.03, "by_tld": {}},
    CommissionService.TRANSFER: {"default": 0.03, "by_tld": {}},
    CommissionService.EMAIL: {"default": 0.0},
    CommissionService.SSL: {"default": 0.0},
    CommissionService.DNSSEC: {"default": 0.0},
    CommissionService.RESTORE: {"default": 0.0},
    CommissionService.EASYDMARC: {"default": 0.0},
    CommissionService.SPAMEXPERTS: {"default": 0.0},
}

_runtime_config: dict[str, Any] = deepcopy(_DEFAULTS)


def load() -> dict[str, Any]:
    """Return an isolated copy of the current process snapshot."""
    return deepcopy(_runtime_config)


def revision() -> str:
    """Stable cache namespace for the currently loaded configuration."""
    encoded = json.dumps(
        _runtime_config,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()[:16]


def _normalise(data: dict[str, Any] | None) -> dict[str, Any]:
    source = data if isinstance(data, dict) else {}
    merged = deepcopy(_DEFAULTS)
    for service, defaults in _DEFAULTS.items():
        supplied = source.get(service)
        if not isinstance(supplied, dict):
            continue
        default_rate = supplied.get("default", defaults["default"])
        try:
            rate = float(default_rate)
        except (TypeError, ValueError):
            rate = float(defaults["default"])
        merged[service]["default"] = min(1.0, max(0.0, rate))
        if service in CommissionService.WITH_TLD:
            overrides: dict[str, float] = {}
            raw_overrides = supplied.get("by_tld")
            if isinstance(raw_overrides, dict):
                for raw_tld, raw_rate in raw_overrides.items():
                    tld = str(raw_tld).strip().lower()
                    if not tld:
                        continue
                    if not tld.startswith("."):
                        tld = f".{tld}"
                    try:
                        override_rate = float(raw_rate)
                    except (TypeError, ValueError):
                        continue
                    overrides[tld] = min(1.0, max(0.0, override_rate))
            merged[service]["by_tld"] = overrides

    if CommissionService.PREMIUM_REGISTRATION not in source:
        registration = merged[CommissionService.REGISTRATION]
        merged[CommissionService.PREMIUM_REGISTRATION] = deepcopy(registration)
    return merged


def _load_legacy_seed() -> dict[str, Any]:
    """Read the old JSON once when upgrading an installation with no DB row."""
    try:
        if _CONFIG_FILE.exists():
            parsed = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                return _normalise(parsed)
    except Exception as exc:
        logger.warning("[COMMISSION] Could not read legacy commission seed: %s", exc)
    return deepcopy(_DEFAULTS)


async def refresh_from_db(session: AsyncSession) -> dict[str, Any]:
    """Refresh this worker from the shared config, seeding legacy installs."""
    global _runtime_config
    repo = PlatformSettingsRepository(session)
    raw = await repo.get(KEY_DOMAIN_COMMISSION_CONFIG)
    if raw is None:
        seeded = _load_legacy_seed()
        try:
            await repo.insert_if_absent(
                KEY_DOMAIN_COMMISSION_CONFIG,
                json.dumps(seeded, separators=(",", ":")),
            )
            await session.commit()
            raw = await repo.get(KEY_DOMAIN_COMMISSION_CONFIG)
        except Exception:
            await session.rollback()
            logger.exception("[COMMISSION] Failed to seed database configuration")
        if raw is None:
            _runtime_config = seeded
            return load()

    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("commission setting is not a JSON object")
        _runtime_config = _normalise(parsed)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.error("[COMMISSION] Invalid database configuration: %s", exc)
        _runtime_config = deepcopy(_DEFAULTS)
    return load()


async def save(session: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    """Validate and persist commission config in the shared database."""
    global _runtime_config
    normalised = _normalise(data)
    repo = PlatformSettingsRepository(session)
    await repo.set(
        KEY_DOMAIN_COMMISSION_CONFIG,
        json.dumps(normalised, separators=(",", ":"), ensure_ascii=False),
    )
    await session.commit()
    _runtime_config = normalised
    logger.info("[COMMISSION] Database commission config saved.")
    return load()


def get_rate(service: str, tld: str | None = None) -> float:
    """Return commission rate (0.0–1.0) for a given service + optional TLD."""
    cfg = load()
    svc = cfg.get(service, {})
    if tld and "by_tld" in svc:
        tld_key = tld if tld.startswith(".") else f".{tld}"
        if tld_key in svc["by_tld"]:
            return float(svc["by_tld"][tld_key])
    return float(svc.get("default", 0.0))


def apply_markup(base_price: float, rate: float) -> float:
    """Apply commission markup: final = base * (1 + rate)."""
    return round(base_price * (1.0 + rate), 2)


def registration_service_for_premium(is_premium: bool) -> str:
    """Map create-registration to the correct commission service key."""
    if is_premium:
        return CommissionService.PREMIUM_REGISTRATION
    return CommissionService.REGISTRATION


def calculate_customer_price(
    provider_price: float,
    *,
    is_premium: bool = False,
    service: str = CommissionService.REGISTRATION,
    currency: str | None = "INR",
    tld: str | None = None,
) -> dict[str, Any]:
    """
    Single pricing path: provider wholesale → FX to INR → admin commission.

    For create registration, ``is_premium`` selects PREMIUM_REGISTRATION vs
    REGISTRATION. Other services use ``service`` as-is.
    GST is applied by callers via the existing GST helpers.
    """
    raw = float(provider_price or 0)
    code = (currency or "INR").upper().strip() or "INR"
    provider_unit_inr = round(raw, 2)
    if code != "INR" and raw > 0:
        from app.service.currency.exchange_rate_service import convert_foreign_to_inr

        try:
            converted = convert_foreign_to_inr(raw, code)
            provider_unit_inr = float(converted["amountInr"])
        except Exception as exc:
            logger.warning(
                "[COMMISSION] FX %s→INR failed for %s: %s; using raw amount",
                code,
                raw,
                exc,
            )
            provider_unit_inr = round(raw, 2)

    if service == CommissionService.REGISTRATION:
        rate_service = registration_service_for_premium(is_premium)
    else:
        rate_service = service

    rate = get_rate(rate_service, tld)
    customer_unit_inr = apply_markup(provider_unit_inr, rate) if provider_unit_inr > 0 else 0.0
    return {
        "providerUnitInr": provider_unit_inr,
        "customerUnitInr": customer_unit_inr,
        "commissionRate": float(rate),
        "commissionService": rate_service,
        "isPremium": bool(is_premium),
        "registryTier": "premium" if is_premium else "standard",
        "currency": "INR",
        "providerCurrency": code,
    }
