"""Domain listing view analytics."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.entity.analytics.domain_listing_view import DomainListingView


class DomainListingViewRepository:
    @staticmethod
    def viewer_has_viewed(
        db: Session,
        entity_id: UUID,
        viewer_id: UUID,
    ) -> bool:
        return (
            db.query(DomainListingView)
            .filter(
                DomainListingView.domain_listing_id == entity_id,
                DomainListingView.viewer_id == viewer_id,
                DomainListingView.is_deleted.is_(False),
            )
            .first()
            is not None
        )

    @staticmethod
    def create_view(
        db: Session,
        *,
        domain_listing_id: UUID,
        viewer_id: UUID | None = None,
        viewer_industry: str | None = None,
        viewer_role: str | None = None,
    ) -> DomainListingView:
        row = DomainListingView(
            domain_listing_id=domain_listing_id,
            viewer_id=viewer_id,
            viewer_industry=viewer_industry,
            viewer_role=viewer_role,
            viewed_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
