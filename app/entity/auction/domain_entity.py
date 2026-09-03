"""
Domain registry — owned assets (e.g. hostnames) eligible for auctions.

UUID PK, soft-delete, timezone-aware timestamps. `owner_id` matches `AppUser.id`.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from app.entity.auction.auction_entity import Auction
    from app.entity.user.app_user import AppUser


class Domain(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A domain name owned by a user; used for auction eligibility."""

    __tablename__ = "domains"

    __table_args__ = (
        Index("idx_domains_owner_id", "owner_id"),
        Index("idx_domains_domain_name", "domain_name"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    domain_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[Optional[str]] = mapped_column(
        String(2000),
        nullable=True,
    )

    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    owner: Mapped["AppUser"] = relationship(
        "AppUser",
        back_populates="domains_owned",
        foreign_keys=[owner_id],
        lazy="selectin",
    )

    auctions: Mapped[List["Auction"]] = relationship(
        "Auction",
        back_populates="domain",
        foreign_keys="Auction.domain_id",
        primaryjoin=(
            "and_(Auction.domain_id==Domain.id, Auction.is_deleted==False)"
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Domain id={self.id} name={self.domain_name!r} owner={self.owner_id}>"



from app.entity.auction.auction_entity import Auction as _Auction  # noqa: F401
