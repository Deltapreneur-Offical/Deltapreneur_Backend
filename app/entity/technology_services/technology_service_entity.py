"""Technology service catalogue model."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class TechnologyServiceEntity(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "technology_services_catalogue"
    __table_args__ = (
        Index("idx_tech_services_slug", "slug", unique=True),
        Index("idx_tech_services_category", "category"),
        Index("idx_tech_services_featured", "is_featured"),
    )

    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    short_description: Mapped[str] = mapped_column(Text, nullable=False)
    long_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    badge: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    features_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    plans_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    faqs_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    price_override_monthly: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_override_annually: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
