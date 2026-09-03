"""Shared helpers for domain marketplace listings."""

from __future__ import annotations

from app.utils.marketplace_enums import SaleType


def listing_type_for(sale_type: SaleType | None) -> str:
    if sale_type == SaleType.AUCTION:
        return "domain_auction"
    return "normal_domain"
