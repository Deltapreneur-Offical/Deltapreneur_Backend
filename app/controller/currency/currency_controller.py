"""Public currency helpers — live INR-base rates with server-side cache."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.service.currency.exchange_rate_service import (
    SUPPORTED_CURRENCIES,
    convert_foreign_to_inr,
    convert_inr,
    get_exchange_rates,
    rates_to_display_meta,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/currency", tags=["Currency"])


@router.get("/supported")
def supported_currencies() -> dict[str, Any]:
    return {"currencies": SUPPORTED_CURRENCIES, "base": "INR"}


@router.get("/rates")
def currency_rates(
    force_refresh: bool = Query(False, alias="forceRefresh"),
) -> dict[str, Any]:
    """All supported conversion rates from INR (cached ~30 minutes on server)."""
    try:
        snapshot = get_exchange_rates(force_refresh=force_refresh)
        return {
            **snapshot,
            "currencies": SUPPORTED_CURRENCIES,
            "meta": rates_to_display_meta(snapshot["rates"]),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("currency.rates.failed err=%s", exc)
        raise HTTPException(
            status_code=502,
            detail="Could not fetch exchange rates. Try again later.",
        ) from exc


@router.get("/convert")
def convert_currency(
    amount: float = Query(..., gt=0, description="Amount in INR"),
    to: str = Query(..., min_length=3, max_length=3),
) -> dict[str, Any]:
    target = to.upper()
    if target not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"Unsupported currency: {to}")
    try:
        return convert_inr(amount, target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning("currency.convert.failed to=%s err=%s", target, exc)
        raise HTTPException(
            status_code=502,
            detail="Could not fetch exchange rates. Try again later.",
        ) from exc


@router.get("/convert-to-inr")
def convert_to_inr(
    amount: float = Query(..., gt=0, description="Amount in foreign currency"),
    from_currency: str = Query(..., min_length=3, max_length=3, alias="from"),
) -> dict[str, Any]:
    """Convert foreign currency → INR using the same live rates as display."""
    source = from_currency.upper()
    if source not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"Unsupported currency: {from_currency}")
    try:
        return convert_foreign_to_inr(amount, source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning("currency.convert_to_inr.failed from=%s err=%s", source, exc)
        raise HTTPException(
            status_code=502,
            detail="Could not fetch exchange rates. Try again later.",
        ) from exc
