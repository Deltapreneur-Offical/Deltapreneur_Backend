"""Virtual Assistant profile view analytics."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.entity.analytics.virtual_assistant_view import VirtualAssistantView


class VirtualAssistantViewRepository:
    @staticmethod
    def viewer_has_viewed(
        db: Session,
        entity_id: UUID,
        viewer_id: UUID,
    ) -> bool:
        return (
            db.query(VirtualAssistantView)
            .filter(
                VirtualAssistantView.application_id == entity_id,
                VirtualAssistantView.viewer_id == viewer_id,
                VirtualAssistantView.is_deleted.is_(False),
            )
            .first()
            is not None
        )

    @staticmethod
    def create_view(
        db: Session,
        *,
        application_id: UUID,
        viewer_id: UUID | None = None,
        viewer_industry: str | None = None,
        viewer_role: str | None = None,
    ) -> VirtualAssistantView:
        row = VirtualAssistantView(
            application_id=application_id,
            viewer_id=viewer_id,
            viewer_industry=viewer_industry,
            viewer_role=viewer_role,
            viewed_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def count_by_application_id(db: Session, application_id: UUID) -> int:
        return int(
            db.query(func.count(VirtualAssistantView.id))
            .filter(
                VirtualAssistantView.application_id == application_id,
                VirtualAssistantView.is_deleted.is_(False),
            )
            .scalar()
            or 0
        )
