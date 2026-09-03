from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.entity.analytics.profile_view import ProfileView
from app.entity.analytics.software_view import SoftwareView
from app.entity.analytics.venture_view import VentureView
from app.repository.profile_view_repository import ProfileViewRepository
from app.repository.software_view_repository import SoftwareViewRepository
from app.repository.venture_view_repository import VentureViewRepository


class AnalyticsRepository:
    """Read/write helpers for venture and profile view analytics."""

    @staticmethod
    def create_venture_view(
        db: Session,
        venture_id: UUID,
        viewer_id: UUID | None = None,
        viewer_industry: str | None = None,
        viewer_role: str | None = None,
    ) -> VentureView:
        return VentureViewRepository.create_view(
            db=db,
            venture_id=venture_id,
            viewer_id=viewer_id,
            viewer_industry=viewer_industry,
            viewer_role=viewer_role,
        )

    @staticmethod
    def create_profile_view(
        db: Session,
        profile_id: UUID,
        viewer_id: UUID | None = None,
        viewer_industry: str | None = None,
        viewer_role: str | None = None,
    ) -> ProfileView:
        return ProfileViewRepository.create_view(
            db=db,
            profile_id=profile_id,
            viewer_id=viewer_id,
            viewer_industry=viewer_industry,
            viewer_role=viewer_role,
        )

    @staticmethod
    def create_software_view(
        db: Session,
        software_id: UUID,
        viewer_id: UUID | None = None,
        viewer_industry: str | None = None,
        viewer_role: str | None = None,
    ) -> SoftwareView:
        return SoftwareViewRepository.create_view(
            db=db,
            software_id=software_id,
            viewer_id=viewer_id,
            viewer_industry=viewer_industry,
            viewer_role=viewer_role,
        )

    @staticmethod
    def list_venture_views(
        db: Session,
        venture_id: UUID,
    ) -> list[VentureView]:
        return VentureViewRepository.get_by_venture_id(
            db=db,
            venture_id=venture_id,
        )

    @staticmethod
    def list_software_views(
        db: Session,
        software_id: UUID,
    ) -> list[SoftwareView]:
        return SoftwareViewRepository.list_by_software_id(
            db=db,
            software_id=software_id,
        )

    @staticmethod
    def list_profile_views(
        db: Session,
        profile_id: UUID,
    ) -> list[ProfileView]:
        return ProfileViewRepository.get_by_profile_id(
            db=db,
            profile_id=profile_id,
        )

    @staticmethod
    def build_daily_timeline(
        timestamps: list[datetime],
        days: int = 30,
    ) -> dict[str, int]:
        """
        Last N calendar days keyed like Java DateTimeFormatter "MMM dd"
        (e.g. May 14). Counts only timestamps whose key falls in that window.
        """
        now = datetime.now(timezone.utc)
        timeline: dict[str, int] = {}

        def day_key(d: datetime) -> str:
            return d.astimezone(timezone.utc).strftime("%b %d")

        for i in range(days):
            day = now - timedelta(days=(days - 1 - i))
            timeline[day_key(day)] = 0

        for ts in timestamps:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            key = day_key(ts)
            if key in timeline:
                timeline[key] = timeline[key] + 1

        return timeline

    @staticmethod
    def count_by_field(values: list[str | None]) -> dict[str, int]:
        filtered = [v for v in values if v is not None and v != ""]
        return dict(Counter(filtered))
