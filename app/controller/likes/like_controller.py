from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.entity.user.app_user import AppUser
from app.model.common.api_response import ApiResponse
from app.service.likes.like_service import LikeService


router = APIRouter(
    prefix="/api/v1/likes",
    tags=["Likes"],
)


@router.get("/test", response_model=ApiResponse)
def test_likes():
    return ApiResponse(
        success=True,
        message="Like module is connected successfully",
        data={
            "module": "likes",
            "status": "ready",
        },
    )


@router.post("/{like_type}/{entity_id}/toggle", response_model=ApiResponse)
def toggle_like(
    like_type: str,
    entity_id: str,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    result = LikeService.toggle_like(
        db=db,
        like_type=like_type,
        entity_id=entity_id,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="Like status updated successfully",
        data=result,
    )


@router.get("/{like_type}/{entity_id}/status", response_model=ApiResponse)
def get_like_status(
    like_type: str,
    entity_id: str,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    result = LikeService.get_like_status(
        db=db,
        like_type=like_type,
        entity_id=entity_id,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="Like status fetched successfully",
        data=result,
    )


@router.get("/{like_type}/my-liked", response_model=ApiResponse)
def get_my_liked_entities(
    like_type: str,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    result = LikeService.get_my_liked_entity_ids(
        db=db,
        like_type=like_type,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="My liked entities fetched successfully",
        data=result,
    )


@router.post("/{like_type}/bulk-counts", response_model=ApiResponse)
def get_bulk_like_counts(
    like_type: str,
    entity_ids: list[str] = Body(..., embed=False),
    db: Session = Depends(get_db),
):
    result = LikeService.get_bulk_counts(
        db=db,
        like_type=like_type,
        entity_ids=entity_ids,
    )

    return ApiResponse(
        success=True,
        message="Bulk like counts fetched successfully",
        data=result,
    )


@router.post("/{like_type}/bulk-status", response_model=ApiResponse)
def get_bulk_like_status(
    like_type: str,
    entity_ids: list[str] = Body(..., embed=False),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    result = LikeService.get_bulk_status(
        db=db,
        like_type=like_type,
        entity_ids=entity_ids,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="Bulk like status fetched successfully",
        data=result,
    )


@router.get("/{like_type}/{entity_id}/who-liked", response_model=ApiResponse)
def get_users_who_liked(
    like_type: str,
    entity_id: str,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    result = LikeService.get_users_who_liked(
        db=db,
        like_type=like_type,
        entity_id=entity_id,
    )

    return ApiResponse(
        success=True,
        message="Users who liked fetched successfully",
        data=result,
    )
