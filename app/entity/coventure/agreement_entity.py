"""Agreement acceptance for venture / marketplace listings."""

from __future__ import annotations

from sqlalchemy import Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Agreement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agreement"

    terms: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
