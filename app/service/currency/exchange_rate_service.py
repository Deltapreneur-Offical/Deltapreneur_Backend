"""Live INR-based exchange rates with in-process cache (30 min TTL)."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Keep in sync with HubRegistrar frontend SUPPORTED_CURRENCIES
SUPPORTED_CURRENCIES = ['AED', 'ALL', 'AMD', 'AUD', 'AWG', 'AZN', 'BAM', 'BBD', 'BDT', 'BGN', 'BHD', 'BIF', 'BMD', 'BND', 'BOB', 'BRL', 'BSD', 'BTN', 'BWP', 'BZD', 'CAD', 'CHF', 'CLP', 'CNY', 'COP', 'CRC', 'CUP', 'CVE', 'CZK', 'DJF', 'DKK', 'DOP', 'DZD', 'EGP', 'ETB', 'EUR', 'FJD', 'GBP', 'GHS', 'GIP', 'GMD', 'GNF', 'GTQ', 'GYD', 'HKD', 'HNL', 'HRK', 'HTG', 'HUF', 'IDR', 'ILS', 'INR', 'IQD', 'ISK', 'JMD', 'JOD', 'JPY', 'KES', 'KGS', 'KHR', 'KMF', 'KRW', 'KWD', 'KYD', 'KZT', 'LAK', 'LKR', 'LRD', 'LSL', 'MAD', 'MDL', 'MGA', 'MKD', 'MMK', 'MNT', 'MOP', 'MUR', 'MVR', 'MWK', 'MXN', 'MYR', 'MZN', 'NAD', 'NGN', 'NIO', 'NOK', 'NPR', 'NZD', 'OMR', 'PEN', 'PGK', 'PHP', 'PKR', 'PLN', 'PYG', 'QAR', 'RON', 'RSD', 'RUB', 'RWF', 'SAR', 'SCR', 'SEK', 'SGD', 'SLL', 'SOS', 'SVC', 'SZL', 'THB', 'TND', 'TRY', 'TTD', 'TWD', 'TZS', 'UAH', 'UGX', 'USD', 'UYU', 'UZS', 'VND', 'VUV', 'XAF', 'XCD', 'XOF', 'XPF', 'YER', 'ZAR', 'ZMW']

_OPEN_ER_API_URL = "https://open.er-api.com/v6/latest/INR"
_EXCHANGE_RATE_API_V4 = "https://api.exchangerate-api.com/v4/latest/INR"
_FLOAT_RATES_URL = "https://www.floatrates.com/daily/inr.json"

# Refresh at most every 30 minutes so displayed FX stays close to "today"
_CACHE_TTL_SECONDS = 1800

_cache_rates: dict[str, float] | None = None
_cache_updated_at: float = 0.0
_cache_source_unix: int | None = None
_cache_providers: list[str] | None = None


def _normalize_snapshot(raw: dict[str, Any]) -> dict[str, float]:
    rates: dict[str, float] = {"INR": 1.0}
    for code in SUPPORTED_CURRENCIES:
        if code == "INR":
            continue
        if code not in raw:
            logger.warning("Rate not available for %s", code)
            continue
        try:
            value = float(raw[code])
            if value <= 0:
                continue
            rates[code] = value
        except (ValueError, TypeError):
            continue
    return rates


def _merge_consumer_rates(snapshots: list[dict[str, float]]) -> dict[str, float]:
    """Lowest INR→foreign rate across providers (matches Wise/Google mid-market better)."""
    merged: dict[str, float] = {"INR": 1.0}
    for code in SUPPORTED_CURRENCIES:
        if code == "INR":
            continue
        candidates = [float(s[code]) for s in snapshots if code in s and float(s[code]) > 0]
        if not candidates:
            logger.warning("No live rate for %s across any provider. Using fallback 1.0", code)
            merged[code] = 1.0
        else:
            merged[code] = min(candidates)
    return merged


def _fetch_open_er_api(client: httpx.Client) -> tuple[dict[str, float], int | None]:
    response = client.get(_OPEN_ER_API_URL)
    response.raise_for_status()
    payload = response.json()
    rates = _normalize_snapshot(payload.get("rates") or {})
    source_unix = payload.get("time_last_update_unix")
    return rates, int(source_unix) if source_unix is not None else None


def _fetch_exchange_rate_api_v4(client: httpx.Client) -> dict[str, float]:
    response = client.get(_EXCHANGE_RATE_API_V4)
    response.raise_for_status()
    payload = response.json()
    return _normalize_snapshot(payload.get("rates") or {})


def _fetch_floatrates(client: httpx.Client) -> dict[str, float]:
    response = client.get(_FLOAT_RATES_URL)
    response.raise_for_status()
    payload = response.json()
    raw: dict[str, float] = {}
    for code in SUPPORTED_CURRENCIES:
        if code == "INR":
            continue
        entry = payload.get(code.lower())
        if entry and entry.get("rate") is not None:
            raw[code] = float(entry["rate"])
    return _normalize_snapshot(raw)


def _fetch_live_rates() -> tuple[dict[str, float], int | None, list[str]]:
    snapshots: list[dict[str, float]] = []
    providers: list[str] = []
    source_unix: int | None = None

    with httpx.Client(timeout=15.0) as client:
        try:
            rates, unix = _fetch_open_er_api(client)
            snapshots.append(rates)
            providers.append("open.er-api")
            source_unix = unix
        except Exception as exc:  # noqa: BLE001
            logger.warning("exchange_rate.open_er_api_failed err=%s", exc)

        try:
            snapshots.append(_fetch_exchange_rate_api_v4(client))
            providers.append("exchangerate-api")
        except Exception as exc:  # noqa: BLE001
            logger.warning("exchange_rate.exchangerate_api_failed err=%s", exc)

        try:
            snapshots.append(_fetch_floatrates(client))
            providers.append("floatrates")
        except Exception as exc:  # noqa: BLE001
            logger.warning("exchange_rate.floatrates_failed err=%s", exc)

    if not snapshots:
        raise RuntimeError("All exchange rate providers failed")

    merged = _merge_consumer_rates(snapshots)
    return merged, source_unix, providers


def get_exchange_rates(*, force_refresh: bool = False) -> dict[str, Any]:
    """
    Return cached or freshly fetched INR-base rates.
    On API failure, returns last good cache if present; otherwise raises.
    """
    global _cache_rates, _cache_updated_at, _cache_source_unix, _cache_providers

    now = time.time()
    if (
        not force_refresh
        and _cache_rates is not None
        and (now - _cache_updated_at) < _CACHE_TTL_SECONDS
    ):
        return {
            "base": "INR",
            "rates": dict(_cache_rates),
            "updatedAt": int(_cache_updated_at),
            "sourceUpdatedAt": _cache_source_unix,
            "cached": True,
            "ttlSeconds": _CACHE_TTL_SECONDS,
            "providers": list(_cache_providers or []),
        }

    try:
        live, source_unix, providers = _fetch_live_rates()
        _cache_rates = live
        _cache_updated_at = now
        _cache_source_unix = source_unix
        _cache_providers = providers
        return {
            "base": "INR",
            "rates": dict(live),
            "updatedAt": int(now),
            "sourceUpdatedAt": source_unix,
            "cached": False,
            "ttlSeconds": _CACHE_TTL_SECONDS,
            "providers": providers,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("exchange_rate.fetch_failed err=%s", exc)
        if _cache_rates is not None:
            return {
                "base": "INR",
                "rates": dict(_cache_rates),
                "updatedAt": int(_cache_updated_at),
                "sourceUpdatedAt": _cache_source_unix,
                "cached": True,
                "stale": True,
                "ttlSeconds": _CACHE_TTL_SECONDS,
                "providers": list(_cache_providers or []),
            }
        raise


def convert_foreign_to_inr(amount: float, from_currency: str) -> dict[str, Any]:
    """Convert a foreign-currency amount to INR for persistence (inverse of convert_inr)."""
    source_code = from_currency.upper()
    if source_code not in SUPPORTED_CURRENCIES:
        raise ValueError(f"Unsupported currency: {from_currency}")
    foreign_amount = float(amount)
    if source_code == "INR":
        return {
            "from": source_code,
            "to": "INR",
            "amountForeign": foreign_amount,
            "amountInr": round(foreign_amount),
            "rate": 1.0,
        }
    snapshot = get_exchange_rates()
    rate = float(snapshot["rates"][source_code])
    if rate <= 0:
        raise ValueError(f"Invalid rate for {source_code}")
    inr_amount = round(foreign_amount / rate)
    return {
        "from": source_code,
        "to": "INR",
        "amountForeign": foreign_amount,
        "amountInr": inr_amount,
        "rate": rate,
        "time_last_update_unix": snapshot.get("sourceUpdatedAt"),
    }


def convert_inr(amount: float, target: str) -> dict[str, Any]:
    target_code = target.upper()
    if target_code not in SUPPORTED_CURRENCIES:
        raise ValueError(f"Unsupported currency: {target}")
    inr_amount = float(amount)
    if target_code == "INR":
        return {
            "from": "INR",
            "to": target_code,
            "amountInr": inr_amount,
            "converted": round(inr_amount, 2),
            "rate": 1.0,
        }
    snapshot = get_exchange_rates()
    rate = float(snapshot["rates"][target_code])
    converted = round(inr_amount * rate, 2)
    return {
        "from": "INR",
        "to": target_code,
        "amountInr": inr_amount,
        "converted": converted,
        "rate": rate,
        "time_last_update_unix": snapshot.get("sourceUpdatedAt"),
    }


def rates_to_display_meta(rates: dict[str, float]) -> dict[str, dict[str, float | str]]:
    """Shape rates for frontend meta: { USD: { rateFromInr, symbol }, ... }."""
    symbols = {
        "INR": "₹",
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
        "AED": "AED",
        "SGD": "S$",
        "AUD": "A$",
        "CAD": "C$",
    }
    meta: dict[str, dict[str, float | str]] = {}
    for code in SUPPORTED_CURRENCIES:
        meta[code] = {
            "symbol": symbols.get(code, f"{code} "),
            "rateFromInr": float(rates.get(code, 1.0 if code == "INR" else 0.0)),
        }
    return meta
