"""Operations service view analytics."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.entity.analytics.operations_service_view import OperationsServiceView


class OperationsServiceViewRepository:
    @staticmethod
    def viewer_has_viewed(
        db: Session,
        entity_id: UUID,
        viewer_id: UUID,
    ) -> bool:
        return (
            db.query(OperationsServiceView)
            .filter(
                OperationsServiceView.operations_service_id == entity_id,
                OperationsServiceView.viewer_id == viewer_id,
                OperationsServiceView.is_deleted.is_(False),
            )
            .first()
            is not None
        )

    @staticmethod
    def create_view(
        db: Session,
        *,
        operations_service_id: UUID,
        viewer_id: UUID | None = None,
        viewer_industry: str | None = None,
        viewer_role: str | None = None,
    ) -> OperationsServiceView:
        row = OperationsServiceView(
            operations_service_id=operations_service_id,
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
    def count_by_service_id(db: Session, service_id: UUID) -> int:
        return int(
            db.query(func.count(OperationsServiceView.id))
            .filter(
                OperationsServiceView.operations_service_id == service_id,
                OperationsServiceView.is_deleted.is_(False),
            )
            .scalar()
            or 0
        )

    @staticmethod
    def bulk_counts(db: Session, service_ids: list[UUID]) -> dict[str, int]:
        if not service_ids:
            return {}
        rows = (
            db.query(
                OperationsServiceView.operations_service_id,
                func.count(OperationsServiceView.id),
            )
            .filter(
                OperationsServiceView.operations_service_id.in_(service_ids),
                OperationsServiceView.is_deleted.is_(False),
            )
            .group_by(OperationsServiceView.operations_service_id)
            .all()
        )
        return {str(row[0]): int(row[1]) for row in rows}
