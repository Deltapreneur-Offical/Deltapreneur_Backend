"""Shopping cart item entity — one row per product in a user's cart."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.cart_enums import CartProductType


class CartItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cart_items"
    __table_args__ = (
        Index("idx_cart_items_user", "user_id"),
        Index(
            "uq_cart_user_product",
            "user_id",
            "product_type",
            "product_id",
            unique=True,
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    product_type: Mapped[CartProductType] = mapped_column(
        SAEnum(
            CartProductType,
            name="cart_product_type_enum",
            create_constraint=False,
            native_enum=False,
        ),
        nullable=False,
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    selected_plan: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    addon_services: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    co_brother_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    metadata_json: Mapped[Optional[dict]] = mapped_column(MutableDict.as_mutable(JSONB), nullable=True)
