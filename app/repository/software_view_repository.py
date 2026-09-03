"""Software listing view analytics — sync Session (matches venture_views)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.entity.analytics.software_view import SoftwareView


class SoftwareViewRepository:
    @staticmethod
    def create_view(
        db: Session,
        software_id: UUID,
        viewer_id: UUID | None = None,
        viewer_industry: str | None = None,
        viewer_role: str | None = None,
    ) -> SoftwareView:
        row = SoftwareView(
            software_id=software_id,
            viewer_id=viewer_id,
            viewer_industry=viewer_industry,
            viewer_role=viewer_role,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def list_by_software_id(db: Session, software_id: UUID) -> list[SoftwareView]:
        return (
            db.query(SoftwareView)
            .filter(
                SoftwareView.software_id == software_id,
                SoftwareView.is_deleted.is_(False),
            )
            .all()
        )

    @staticmethod
    def viewer_has_viewed(
        db: Session,
        software_id: UUID,
        viewer_id: UUID,
    ) -> bool:
        return (
            db.query(SoftwareView)
            .filter(
                SoftwareView.software_id == software_id,
                SoftwareView.viewer_id == viewer_id,
                SoftwareView.is_deleted.is_(False),
            )
            .first()
            is not None
        )

    @staticmethod
    def recent_view_exists(
        db: Session,
        software_id: UUID,
        viewer_id: UUID,
        minutes: int = 5,
    ) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        return (
            db.query(SoftwareView)
            .filter(
                SoftwareView.software_id == software_id,
                SoftwareView.viewer_id == viewer_id,
                SoftwareView.viewed_at >= cutoff,
                SoftwareView.is_deleted.is_(False),
            )
            .first()
            is not None
        )
