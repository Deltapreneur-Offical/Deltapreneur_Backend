"""Operations virtual-assistant service catalog."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class OperationsService(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "operations_services"
    __table_args__ = (
        Index(
            "idx_operations_services_public_browse",
            "is_deleted",
            "is_available",
            "display_order",
        ),
        Index("idx_operations_services_category", "category"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    icon: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skills: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    service_type: Mapped[str] = mapped_column(
        String(32),
        default="virtual_assistance",
        nullable=False,
    )
    government_fees_applicable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    government_fee_text: Mapped[str] = mapped_column(String(255), default="Government fees applicable", nullable=False)
