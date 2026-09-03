from uuid import UUID

from sqlalchemy.orm import Session

from app.repository.analytics_repository import (
    AnalyticsRepository
)

from app.repository.software_view_repository import SoftwareViewRepository
from app.repository.venture_view_repository import (
    VentureViewRepository
)


async def track_venture_view(
    db: Session,
    venture_id: UUID,
    viewer_id: UUID | None = None,
    viewer_industry: str | None = None,
    viewer_role: str | None = None
):

    if viewer_id is not None:

        already_exists = (
            VentureViewRepository.recent_view_exists(
                db=db,
                venture_id=venture_id,
                viewer_id=viewer_id
            )
        )

        if already_exists:

            return {
                "success": True,
                "message": "Recent venture view already tracked",
                "data": None
            }

    AnalyticsRepository.create_venture_view(
        db=db,
        venture_id=venture_id,
        viewer_id=viewer_id,
        viewer_industry=viewer_industry,
        viewer_role=viewer_role
    )

    return {
        "success": True,
        "message": "Venture view tracked successfully",
        "data": None
    }


async def track_software_view(
    db: Session,
    software_id: UUID,
    viewer_id: UUID | None = None,
    viewer_industry: str | None = None,
    viewer_role: str | None = None,
):
    if viewer_id is not None:
        if SoftwareViewRepository.recent_view_exists(
            db=db,
            software_id=software_id,
            viewer_id=viewer_id,
        ):
            return {
                "success": True,
                "message": "Recent software view already tracked",
                "data": None,
            }

    AnalyticsRepository.create_software_view(
        db=db,
        software_id=software_id,
        viewer_id=viewer_id,
        viewer_industry=viewer_industry,
        viewer_role=viewer_role,
    )

    return {
        "success": True,
        "message": "Software view tracked successfully",
        "data": None,
    }


async def track_profile_view(
    db: Session,
    profile_id: UUID,
    viewer_id: UUID | None = None,
    viewer_industry: str | None = None,
    viewer_role: str | None = None
):

    if viewer_id is not None:
        from app.repository.profile_view_repository import ProfileViewRepository

        if ProfileViewRepository.recent_view_exists(
            db=db,
            profile_id=profile_id,
            viewer_id=viewer_id,
        ):
            return {
                "success": True,
                "message": "Recent profile view already tracked",
                "data": None,
            }

    AnalyticsRepository.create_profile_view(
        db=db,
        profile_id=profile_id,
        viewer_id=viewer_id,
        viewer_industry=viewer_industry,
        viewer_role=viewer_role
    )

    return {
        "success": True,
        "message": "Profile view tracked successfully",
        "data": None
    }