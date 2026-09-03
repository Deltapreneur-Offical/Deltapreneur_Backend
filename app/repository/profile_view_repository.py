from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.entity.analytics.profile_view import (
    ProfileView
)


class ProfileViewRepository:

    @staticmethod
    def create_view(
        db: Session,
        profile_id: UUID,
        viewer_id: UUID | None = None,
        viewer_industry: str | None = None,
        viewer_role: str | None = None
    ):

        profile_view = ProfileView(
            profile_id=profile_id,
            viewer_id=viewer_id,
            viewer_industry=viewer_industry,
            viewer_role=viewer_role
        )

        db.add(profile_view)

        db.commit()

        db.refresh(profile_view)

        return profile_view

    @staticmethod
    def viewer_has_viewed(
        db: Session,
        profile_id: UUID,
        viewer_id: UUID,
    ) -> bool:
        return (
            db.query(ProfileView)
            .filter(
                ProfileView.profile_id == profile_id,
                ProfileView.viewer_id == viewer_id,
                ProfileView.is_deleted.is_(False),
            )
            .first()
            is not None
        )

    @staticmethod
    def recent_view_exists(
        db: Session,
        profile_id: UUID,
        viewer_id: UUID,
        minutes: int = 5,
    ):
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)

        return (
            db.query(ProfileView)
            .filter(
                ProfileView.profile_id == profile_id,
                ProfileView.viewer_id == viewer_id,
                ProfileView.viewed_at >= cutoff,
                ProfileView.is_deleted.is_(False),
            )
            .first()
            is not None
        )

    @staticmethod
    def get_by_profile_id(
        db: Session,
        profile_id: UUID
    ):

        return (
            db.query(ProfileView)
            .filter(
                ProfileView.profile_id == profile_id,
                ProfileView.is_deleted.is_(False)
            )
            .order_by(ProfileView.viewed_at.desc())
            .all()
        )

    @staticmethod
    def count_unique_viewers(
        db: Session,
        profile_id: UUID,
    ) -> int:
        return int(
            db.query(func.count(func.distinct(ProfileView.viewer_id)))
            .filter(
                ProfileView.profile_id == profile_id,
                ProfileView.viewer_id.isnot(None),
                ProfileView.is_deleted.is_(False),
            )
            .scalar()
            or 0
        )

    @staticmethod
    def bulk_unique_viewer_counts(
        db: Session,
        profile_ids: list[UUID],
    ) -> dict[str, int]:
        if not profile_ids:
            return {}

        rows = (
            db.query(
                ProfileView.profile_id,
                func.count(func.distinct(ProfileView.viewer_id)),
            )
            .filter(
                ProfileView.profile_id.in_(profile_ids),
                ProfileView.viewer_id.isnot(None),
                ProfileView.is_deleted.is_(False),
            )
            .group_by(ProfileView.profile_id)
            .all()
        )
        return {str(row[0]): int(row[1]) for row in rows}

    @staticmethod
    def count_by_profile_id(
        db: Session,
        profile_id: UUID
    ):

        return (
            db.query(func.count(ProfileView.id))
            .filter(
                ProfileView.profile_id == profile_id,
                ProfileView.is_deleted.is_(False)
            )
            .scalar()
        )
