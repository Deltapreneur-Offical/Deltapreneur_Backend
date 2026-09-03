"""Hub Registrar Office entity."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class HubRegistrarOffice(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "hub_registrar_offices"
    __table_args__ = (
        Index(
            "idx_hub_registrar_offices_public_browse",
            "is_deleted",
            "is_active",
            "display_order",
        ),
        Index("idx_hub_registrar_offices_active", "is_active"),
    )

    office_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    full_address: Mapped[str] = mapped_column(Text, nullable=False)
    map_link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    zone: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
