"""Hub Registrar main category catalog."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class HubRegistrarCategory(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "hub_registrar_categories"
    __table_args__ = (
        Index(
            "idx_hub_registrar_categories_public_browse",
            "is_deleted",
            "is_active",
            "display_order",
        ),
        Index("idx_hub_registrar_categories_slug", "slug", unique=True),
    )

    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    starting_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
