import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.entity.user.app_user import AppUser
from app.model.common.api_response import ApiResponse
from app.model.community.community_comment_request import CommunityCommentRequest
from app.model.community.community_post_request import CommunityPostRequest
from app.service.community.community_post_service import CommunityPostService


router = APIRouter(
    prefix="/api/v1/community-posts",
    tags=["Community Posts"],
)


@router.get("/test", response_model=ApiResponse)
def test_community_posts():
    return ApiResponse(
        success=True,
        message="Community post module is connected successfully",
        data={
            "module": "community-posts",
            "status": "ready",
        },
    )


@router.post("", response_model=ApiResponse)
def create_community_post(
    request: CommunityPostRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    post = CommunityPostService.create_post(
        db=db,
        request=request,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="Community post created successfully",
        data=post,
    )


@router.get("/all", response_model=ApiResponse)
def get_all_community_posts(
    db: Session = Depends(get_db),
):
    posts = CommunityPostService.get_all_posts(db)

    return ApiResponse(
        success=True,
        message="Community posts fetched successfully",
        data=posts,
    )


@router.get("/my", response_model=ApiResponse)
def get_my_community_posts(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    posts = CommunityPostService.get_my_posts(
        db=db,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="My community posts fetched successfully",
        data=posts,
    )


@router.get("/community/{community_id}", response_model=ApiResponse)
def get_posts_by_community(
    community_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    posts = CommunityPostService.get_posts_by_community(
        db=db,
        community_id=community_id,
    )

    return ApiResponse(
        success=True,
        message="Community posts fetched successfully",
        data=posts,
    )


@router.get("/{post_id}", response_model=ApiResponse)
def get_community_post_by_id(
    post_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    post = CommunityPostService.get_post_by_id(
        db=db,
        post_id=post_id,
    )

    return ApiResponse(
        success=True,
        message="Community post fetched successfully",
        data=post,
    )


@router.delete("/{post_id}", response_model=ApiResponse)
def delete_community_post(
    post_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    CommunityPostService.delete_post(
        db=db,
        post_id=post_id,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="Community post deleted successfully",
        data=None,
    )


@router.post("/{post_id}/comments", response_model=ApiResponse)
def add_community_comment(
    post_id: uuid.UUID,
    request: CommunityCommentRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    comment = CommunityPostService.add_comment(
        db=db,
        post_id=post_id,
        request=request,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="Community comment added successfully",
        data=comment,
    )


@router.get("/{post_id}/comments", response_model=ApiResponse)
def get_community_comments(
    post_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    comments = CommunityPostService.get_comments_by_post(
        db=db,
        post_id=post_id,
    )

    return ApiResponse(
        success=True,
        message="Community comments fetched successfully",
        data=comments,
    )


@router.delete("/comments/{comment_id}", response_model=ApiResponse)
def delete_community_comment(
    comment_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    CommunityPostService.delete_comment(
        db=db,
        comment_id=comment_id,
        current_user=current_user,
    )

    return ApiResponse(
        success=True,
        message="Community comment deleted successfully",
        data=None,
    )
