"""Runtime-editable commission/markup config for domain services.

Stored in <backend_root>/data/domain_commission.json so it persists across
restarts without a database migration. The file is created with defaults on
first read.

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
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_CONFIG_FILE = _DATA_DIR / "domain_commission.json"


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

_lock = threading.Lock()


def _ensure_data_dir() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def load() -> dict[str, Any]:
    """Load current commission config, creating defaults if missing."""
    with _lock:
        try:
            if _CONFIG_FILE.exists():
                raw = _CONFIG_FILE.read_text(encoding="utf-8")
                data = json.loads(raw)
                merged = dict(_DEFAULTS)
                for key, default_val in _DEFAULTS.items():
                    if key in data:
                        merged[key] = {**default_val, **data[key]}
                # Seed premium_registration from registration when absent on disk
                # so existing installs do not jump to a different default.
                if CommissionService.PREMIUM_REGISTRATION not in data:
                    reg = merged.get(CommissionService.REGISTRATION) or {}
                    merged[CommissionService.PREMIUM_REGISTRATION] = {
                        "default": float(reg.get("default", 0.03)),
                        "by_tld": dict(reg.get("by_tld") or {}),
                    }
                return merged
        except Exception as exc:
            logger.warning("[COMMISSION] Failed to read commission config: %s", exc)
        _ensure_data_dir()
        try:
            _CONFIG_FILE.write_text(json.dumps(_DEFAULTS, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("[COMMISSION] Could not write default commission config: %s", exc)
        return dict(_DEFAULTS)


def save(data: dict[str, Any]) -> None:
    """Persist commission config to disk."""
    with _lock:
        _ensure_data_dir()
        _CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("[COMMISSION] Commission config saved.")


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
