"""Brand details embeddable stored as its own UUID row."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.venture_enums import Industry, VentureType


class BrandDetails(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "brand_details"

    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    brand_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    industry: Mapped[Optional[Industry]] = mapped_column(
        SAEnum(Industry, name="industry_enum", create_constraint=False),
        nullable=True,
    )
    deal_value: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    seller_deal_value: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    venture_image_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    venture_type: Mapped[Optional[VentureType]] = mapped_column(
        SAEnum(VentureType, name="venture_type_enum", create_constraint=False),
        nullable=True,
    )
