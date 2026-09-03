"""Supporting documents uploaded for venture listing verification."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.entity.coventure.venture_entity import Venture


class VentureVerificationDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "venture_verification_documents"
    __table_args__ = (Index("idx_venture_verification_documents_venture_id", "venture_id"),)

    venture_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ventures.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    venture: Mapped["Venture"] = relationship(
        "Venture",
        back_populates="verification_documents",
        foreign_keys=[venture_id],
    )
