from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.entity.user.app_user import AppUser

from app.core.dependencies import get_current_user
from app.core.database import get_db

from app.service.analytics.analytics_service import (
    get_venture_analytics,
    get_profile_analytics
)

from app.service.analytics.tracking_service import (
    track_venture_view,
    track_profile_view
)

from app.model.analytics.profile_analytics_response import (
    ProfileAnalyticsResponse
)

from app.model.analytics.venture_analytics_response import (
    VentureAnalyticsResponse
)


router = APIRouter(
    prefix="/api/v1/analytics",
    tags=["Analytics"]
)


@router.get(
    "/venture/{venture_id}",
    response_model=VentureAnalyticsResponse
)
async def venture_analytics(
    venture_id: UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user)
):

    return await get_venture_analytics(
        db=db,
        venture_id=venture_id,
        current_user=current_user
    )


@router.post("/venture/{venture_id}/track")
async def track_venture_analytics(
    venture_id: UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user)
):

    await track_venture_view(
        db=db,
        venture_id=venture_id,
        viewer_id=current_user.id,
    )

    return {
        "success": True,
        "message": "Venture view tracked successfully"
    }


@router.get(
    "/profile",
    response_model=ProfileAnalyticsResponse
)
async def profile_analytics(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user)
):

    return await get_profile_analytics(
        db=db,
        current_user=current_user
    )


@router.post("/profile/{profile_id}/track")
async def track_profile_analytics(
    profile_id: UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user)
):

    await track_profile_view(
        db=db,
        profile_id=profile_id,
        viewer_id=current_user.id,
    )

    return {
        "success": True,
        "message": "Profile view tracked successfully"
    }
