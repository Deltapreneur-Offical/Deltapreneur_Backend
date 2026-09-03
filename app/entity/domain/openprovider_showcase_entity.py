"""OpenProvider Premium Showcase domains (admin-curated, isolated from marketplace).

This table ONLY stores showcase selection/candidate metadata for the OP Premium
Showcase feature. It is deliberately NOT linked to domain_listings, orders, cart
items, or any marketplace escrow/acquisition flow.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class OpenProviderShowcaseDomain(
    UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base
):
    __tablename__ = "openprovider_showcase_domains"

    domain_name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    # Seed keyword that discovered this domain (audit trail).
    label: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tld: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # OP registry premium flag snapshot at generation time.
    is_premium: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Only "registry" rows are ever stored; aftermarket never persisted.
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="registry")
    # Price SNAPSHOTS for card display — checkout always live-revalidates.
    create_price_inr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    renewal_price_inr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # GST-inclusive payable (create price breakdown) — drives ₹5L under/over + managed hint.
    payable_inr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_snapshot_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # THE public switch: only is_selected=True rows ever appear in the feed.
    is_selected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
