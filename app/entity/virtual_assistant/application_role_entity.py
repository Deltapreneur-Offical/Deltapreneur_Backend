from __future__ import annotations

import uuid

from sqlalchemy import Enum, String, Text, DateTime, ForeignKey, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

class ApplicationRole(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "virtual_assistant_application_roles"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("virtual_assistant_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("pending", "approved", "rejected", name="role_status_enum"),
        default="pending",
        nullable=False,
    )
    reviewed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    rejection_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_clients: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_clients: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    application = relationship("VirtualAssistantApplication", back_populates="application_roles")
