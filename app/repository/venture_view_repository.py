from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.entity.analytics.venture_view import VentureView


class VentureViewRepository:

    @staticmethod
    def create_view(
        db: Session,
        venture_id: UUID,
        viewer_id: UUID | None = None,
        viewer_industry: str | None = None,
        viewer_role: str | None = None
    ):

        venture_view = VentureView(
            venture_id=venture_id,
            viewer_id=viewer_id,
            viewer_industry=viewer_industry,
            viewer_role=viewer_role
        )

        db.add(venture_view)

        db.commit()

        db.refresh(venture_view)

        return venture_view

    @staticmethod
    def get_by_venture_id(
        db: Session,
        venture_id: UUID
    ):

        return (
            db.query(VentureView)
            .filter(
                VentureView.venture_id == venture_id,
                VentureView.is_deleted.is_(False)
            )
            .all()
        )

    @staticmethod
    def count_by_venture_id(
        db: Session,
        venture_id: UUID
    ):

        return (
            db.query(func.count(VentureView.id))
            .filter(
                VentureView.venture_id == venture_id,
                VentureView.is_deleted.is_(False)
            )
            .scalar()
        )
    @staticmethod
    def viewer_has_viewed(
        db: Session,
        venture_id: UUID,
        viewer_id: UUID,
    ) -> bool:
        return (
            db.query(VentureView)
            .filter(
                VentureView.venture_id == venture_id,
                VentureView.viewer_id == viewer_id,
                VentureView.is_deleted.is_(False),
            )
            .first()
            is not None
        )

    @staticmethod
    def recent_view_exists(
        db: Session,
        venture_id: UUID,
        viewer_id: UUID,
        minutes: int = 5
    ):

        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(
            timezone.utc
        ) - timedelta(minutes=minutes)

        return (
            db.query(VentureView)
            .filter(
                VentureView.venture_id == venture_id,
                VentureView.viewer_id == viewer_id,
                VentureView.viewed_at >= cutoff,
                VentureView.is_deleted.is_(False)
            )
            .first()
            is not None
        )
