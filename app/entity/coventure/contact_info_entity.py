"""Contact info for venture / marketplace listings."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ContactInfo(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "contact_info"

    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
