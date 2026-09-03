import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class ShareType(str, enum.Enum):
    """Shareable entity kinds supported by the generic share-link system."""

    MARKETPLACE = "MARKETPLACE"
    DOMAIN_SEARCH = "DOMAIN_SEARCH"
    AI_BRAND_DOMAIN = "AI_BRAND_DOMAIN"


class ShareStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class ShareLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One shareable link.

    ``referrer_id`` is always derived server-side from the authenticated share
    creator — the client can never name a referrer. ``listing_id`` is set only
    for MARKETPLACE shares; ``domain`` only for DOMAIN_SEARCH / AI_BRAND_DOMAIN
    shares. The original search / AI prompt is preserved in ``original_query``.
    Prices and availability are NEVER stored here — every preview re-runs a live
    registrar check.
    """

    __tablename__ = "share_links"

    token: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        unique=True,
        index=True,
    )
    share_type: Mapped[ShareType] = mapped_column(
        Enum(ShareType, name="share_type_enum"),
        nullable=False,
        index=True,
    )
    # NULL when the share was created by a logged-out user — such shares carry
    # no referrer and therefore can never earn an Edge Points reward (the server
    # never fabricates an anonymous referrer).
    referrer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    listing_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("domain_listings.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    domain: Mapped[str | None] = mapped_column(
        String(253),
        nullable=True,
        index=True,
    )
    original_query: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    # Optional self-referral hardening: the sender's own anonymous visitor key
    # at share-creation time, so "sender logs out and opens own link in the
    # same browser" can be detected via the signed cb_visitor cookie.
    referrer_visitor_key: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    status: Mapped[ShareStatus] = mapped_column(
        Enum(ShareStatus, name="share_status_enum"),
        default=ShareStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "(share_type = 'MARKETPLACE' AND listing_id IS NOT NULL AND domain IS NULL) "
            "OR (share_type IN ('DOMAIN_SEARCH', 'AI_BRAND_DOMAIN') "
            "AND domain IS NOT NULL AND listing_id IS NULL)",
            name="ck_share_links_item_reference",
        ),
        Index(
            "ix_share_links_referrer_domain",
            "referrer_id",
            "share_type",
            "domain",
        ),
    )
