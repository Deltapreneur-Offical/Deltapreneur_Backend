"""Join CoBrother (Be the Disruptive CoBrother) application."""

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BeCoBrotherApplication(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "be_cobrother_applications"

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pin_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    skill: Mapped[str | None] = mapped_column(String(100), nullable=True)
    equipment: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
