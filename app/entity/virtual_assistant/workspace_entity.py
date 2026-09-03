"""Virtual Assistant Workspace entities (assignments, clients, notifications)."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    String,
    Text,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin
from app.entity.virtual_assistant.virtual_assistant_entity import (
    VirtualAssistantApplication,
)


class VAAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "va_assignments"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("virtual_assistant_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    assigned_company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    assigned_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    start_date: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    application = relationship("VirtualAssistantApplication", back_populates="assignments")


class VAClient(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "va_clients"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("virtual_assistant_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    assigned_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(
            "active",
            "completed",
            "inactive",
            name="va_client_status_enum",
        ),
        default="active",
        nullable=False,
    )

    application = relationship("VirtualAssistantApplication", back_populates="clients")


class VANotification(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "va_notifications"

    va_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    notification_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    related_application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("virtual_assistant_applications.id", ondelete="CASCADE"),
        nullable=True,
    )
    related_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("va_assignments.id", ondelete="CASCADE"),
        nullable=True,
    )

    assignment = relationship(
        "VAAssignment",
        primaryjoin="VANotification.related_assignment_id == VAAssignment.id",
        viewonly=True,
    )
