"""Uploaded documents attached to a venture listing."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.entity.coventure.venture_entity import Venture


class VentureDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "venture_documents"

    venture_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ventures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    file_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    venture: Mapped["Venture"] = relationship(
        "Venture",
        back_populates="documents",
        foreign_keys=[venture_id],
    )
