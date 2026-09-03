from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.entity.community.community import Community
from app.entity.coventure.partner_entity import CoVenture
from app.entity.coventure.venture_entity import Venture
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.repository.analytics_repository import AnalyticsRepository


def _venture_view_timestamps(views):
    return [v.viewed_at for v in views]


def _profile_view_timestamps(views):
    return [v.viewed_at for v in views]


def _parse_skills(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _merge_legacy_view_total(
    views_by_day: dict[str, int],
    tracked_total: int,
    legacy_total: int,
) -> tuple[int, dict[str, int]]:
    total_views = max(tracked_total, legacy_total)
    if legacy_total <= tracked_total or not views_by_day:
        return total_views, views_by_day

    today_key = datetime.now(timezone.utc).strftime("%b %d")
    merged = dict(views_by_day)
    if today_key in merged:
        merged[today_key] = merged[today_key] + (legacy_total - tracked_total)
    return total_views, merged


def _coventure_metrics(
    db: Session,
    venture: Venture,
    views,
) -> tuple[int, dict[str, int], dict[str, int], float]:
    applications = (
        db.query(CoVenture)
        .filter(CoVenture.venture_id == venture.id)
        .all()
    )
    total_apps = max(len(applications), int(venture.co_venture_application_count or 0))

    by_status: dict[str, int] = dict(
        Counter(
            app.status.value if hasattr(app.status, "value") else str(app.status)
            for app in applications
        )
    )

    applicant_skills: Counter[str] = Counter()
    hours_to_apply: list[float] = []
    views_by_viewer: dict[UUID, list[datetime]] = {}

    for view in views:
        if view.viewer_id:
            viewed_at = view.viewed_at
            if viewed_at and viewed_at.tzinfo is None:
                viewed_at = viewed_at.replace(tzinfo=timezone.utc)
            views_by_viewer.setdefault(view.viewer_id, []).append(viewed_at)

    for app in applications:
        community = (
            db.query(Community)
            .filter(
                Community.app_user_id == app.applicant_user_id,
                Community.is_deleted.is_(False),
            )
            .first()
        )
        if community and community.skills:
            for skill in _parse_skills(community.skills):
                applicant_skills[skill] += 1

        viewer_views = views_by_viewer.get(app.applicant_user_id, [])
        if not viewer_views or not app.created_at:
            continue

        first_view = min(viewer_views)
        applied_at = app.created_at
        if applied_at.tzinfo is None:
            applied_at = applied_at.replace(tzinfo=timezone.utc)
        if first_view >= applied_at:
            continue
        hours_to_apply.append((applied_at - first_view).total_seconds() / 3600)

    avg_hours_to_apply = (
        round(sum(hours_to_apply) / len(hours_to_apply), 1)
        if hours_to_apply
        else 0.0
    )

    return total_apps, by_status, dict(applicant_skills), avg_hours_to_apply


async def get_venture_analytics(
    db: Session,
    venture_id: UUID,
    current_user: AppUser,
):
    if not venture_id or not current_user.id:
        return {
            "success": False,
            "message": "Invalid request",
            "data": None,
        }

    venture = _require_venture_owner(db, venture_id, current_user)

    views = AnalyticsRepository.list_venture_views(db, venture_id)
    tracked_total = len(views)

    views_by_day = AnalyticsRepository.build_daily_timeline(
        _venture_view_timestamps(views),
        30,
    )
    legacy_total = int(venture.views or 0) if venture is not None else 0
    total_views, views_by_day = _merge_legacy_view_total(
        views_by_day,
        tracked_total,
        legacy_total,
    )

    by_industry = AnalyticsRepository.count_by_field(
        [v.viewer_industry for v in views]
    )
    by_role = AnalyticsRepository.count_by_field(
        [v.viewer_role for v in views]
    )

    if venture is None:
        total_apps = 0
        by_status: dict[str, int] = {}
        applicant_skills: dict[str, int] = {}
        avg_hours_to_apply = 0.0
        venture_name = None
    else:
        total_apps, by_status, applicant_skills, avg_hours_to_apply = _coventure_metrics(
            db,
            venture,
            views,
        )
        venture_name = (
            venture.brand_details.brand_name
            if venture.brand_details and venture.brand_details.brand_name
            else None
        )
    conversion_rate = (
        round((total_apps / total_views) * 100, 1) if total_views > 0 else 0.0
    )

    return {
        "success": True,
        "message": "Venture analytics fetched successfully",
        "data": {
            "ventureId": str(venture_id),
            "ventureName": venture_name,
            "totalViews": total_views,
            "totalApplications": total_apps,
            "conversionRate": conversion_rate,
            "avgHoursToApply": avg_hours_to_apply,
            "viewsByDay": views_by_day,
            "byIndustry": by_industry,
            "byRole": by_role,
            "applicantSkills": applicant_skills,
            "byStatus": by_status,
        },
    }


async def get_profile_analytics(
    db: Session,
    current_user: AppUser,
):
    """
    Profile analytics for the current user.

    MVP: `profile_views.profile_id` is the profile owner's user id until
    `Community` exists and ids align with Java `profile.getId()`.
    """
    if not current_user.id:
        return {
            "success": False,
            "message": "Invalid request",
            "data": None,
        }

    profile_id = current_user.id
    views = AnalyticsRepository.list_profile_views(db, profile_id)

    one_week_ago = datetime_now_utc() - timedelta(days=7)

    this_week = 0

    for view in views:

        if view.viewed_at is None:
            continue

        viewed_at = view.viewed_at

        if viewed_at.tzinfo is None:
            viewed_at = viewed_at.replace(
                tzinfo=timezone.utc
            )

        if viewed_at > one_week_ago:
            this_week += 1


    views_by_day = AnalyticsRepository.build_daily_timeline(
        _profile_view_timestamps(views),
        30,
    )

    by_industry = AnalyticsRepository.count_by_field(
        [v.viewer_industry for v in views]
    )

    by_role = AnalyticsRepository.count_by_field(
        [v.viewer_role for v in views]
    )

    return {
    "success": True,
    "data": {
        "totalViews": len(views),
        "viewsThisWeek": this_week,
        "viewsByDay": views_by_day,
        "byIndustry": by_industry,
        "byRole": by_role,
    }
}


def datetime_now_utc():
    return datetime.now(timezone.utc)


def _require_venture_owner(
    db: Session,
    venture_id: UUID,
    current_user: AppUser,
) -> Venture | None:
    venture = (
        db.query(Venture)
        .filter(Venture.id == venture_id, Venture.is_deleted.is_(False))
        .first()
    )
    if venture is None:
        if AnalyticsRepository.list_venture_views(db, venture_id):
            return None
        raise AppException("Venture not found", status_code=404)

    role_value = (
        current_user.role.value
        if hasattr(current_user.role, "value")
        else str(current_user.role)
    )
    is_admin = role_value in {UserRole.ADMIN.value, "ROLE_ADMIN"}
    if not is_admin and venture.listed_by_user_id != current_user.id:
        raise AppException("Access denied", status_code=403)

    return venture
