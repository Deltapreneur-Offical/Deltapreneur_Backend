import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.entity.community.community_comment import CommunityComment
from app.entity.community.community_post import CommunityPost
from app.entity.notification.notification_type import NotificationType
from app.entity.user.app_user import AppUser
from app.model.community.community_comment_request import CommunityCommentRequest
from app.model.community.community_post_request import CommunityPostRequest
from app.repository.community_comment_repository import CommunityCommentRepository
from app.repository.community_post_repository import CommunityPostRepository
from app.repository.community_repository import CommunityRepository
from app.repository.user_repository import UserRepository
from app.integrations.s3.supabase_storage import resolve_media_url
from app.service.notification.notification_service import NotificationService


class CommunityPostService:
    @staticmethod
    def _post_to_response(post: CommunityPost) -> dict:
        resolved_image = resolve_media_url(post.image_url)
        return {
            "id": str(post.id),
            "community_id": str(post.community_id),
            "author_id": str(post.author_id),
            "title": post.title,
            "content": post.content,
            "image_url": resolved_image,
            "imageUrl": resolved_image,
            "created_at": post.created_at.isoformat() if post.created_at else None,
            "updated_at": post.updated_at.isoformat() if post.updated_at else None,
            "createdAt": post.created_at.isoformat() if post.created_at else None,
            "updatedAt": post.updated_at.isoformat() if post.updated_at else None,
        }

    @staticmethod
    def _comment_to_response(comment: CommunityComment) -> dict:
        return {
            "id": str(comment.id),
            "post_id": str(comment.post_id),
            "author_id": str(comment.author_id),
            "content": comment.content,
            "created_at": comment.created_at.isoformat() if comment.created_at else None,
            "updated_at": comment.updated_at.isoformat() if comment.updated_at else None,
        }

    @staticmethod
    def create_post(
        db: Session,
        request: CommunityPostRequest,
        current_user: AppUser,
    ) -> dict:
        try:
            community_id = uuid.UUID(request.community_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid community_id",
            ) from None

        community = CommunityRepository.find_by_id(
            db=db,
            community_id=community_id,
        )

        if not community:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Creator profile not found",
            )

        post = CommunityPost(
            community_id=community_id,
            author_id=current_user.id,
            title=request.title,
            content=request.content,
            image_url=request.image_url,
        )

        saved_post = CommunityPostRepository.save(
            db=db,
            post=post,
        )

        return CommunityPostService._post_to_response(saved_post)

    @staticmethod
    def get_all_posts(db: Session) -> list[dict]:
        posts = CommunityPostRepository.find_all(db)

        return [
            CommunityPostService._post_to_response(post)
            for post in posts
        ]

    @staticmethod
    def get_posts_by_community(
        db: Session,
        community_id: uuid.UUID,
    ) -> list[dict]:
        community = CommunityRepository.find_by_id(
            db=db,
            community_id=community_id,
        )

        if not community:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Creator profile not found",
            )

        posts = CommunityPostRepository.find_by_community_id(
            db=db,
            community_id=community_id,
        )

        return [
            CommunityPostService._post_to_response(post)
            for post in posts
        ]

    @staticmethod
    def get_my_posts(
        db: Session,
        current_user: AppUser,
    ) -> list[dict]:
        posts = CommunityPostRepository.find_by_author_id(
            db=db,
            author_id=current_user.id,
        )

        return [
            CommunityPostService._post_to_response(post)
            for post in posts
        ]

    @staticmethod
    def get_post_by_id(
        db: Session,
        post_id: uuid.UUID,
    ) -> dict:
        post = CommunityPostRepository.find_by_id(
            db=db,
            post_id=post_id,
        )

        if not post:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Community post not found",
            )

        return CommunityPostService._post_to_response(post)

    @staticmethod
    def delete_post(
        db: Session,
        post_id: uuid.UUID,
        current_user: AppUser,
    ) -> None:
        post = CommunityPostRepository.find_by_id(
            db=db,
            post_id=post_id,
        )

        if not post:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Community post not found",
            )

        if post.author_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete your own post",
            )

        CommunityPostRepository.soft_delete(
            db=db,
            post=post,
            deleted_by=current_user.id,
        )

    @staticmethod
    def add_comment(
        db: Session,
        post_id: uuid.UUID,
        request: CommunityCommentRequest,
        current_user: AppUser,
    ) -> dict:
        post = CommunityPostRepository.find_by_id(
            db=db,
            post_id=post_id,
        )

        if not post:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Community post not found",
            )

        comment = CommunityComment(
            post_id=post_id,
            author_id=current_user.id,
            content=request.content,
        )

        saved_comment = CommunityCommentRepository.save(
            db=db,
            comment=comment,
        )

        if post.author_id != current_user.id:
            post_author = UserRepository.find_by_id(
                db=db,
                user_id=post.author_id,
            )

            if post_author:
                NotificationService.notify(
                    db=db,
                    user=post_author,
                    notification_type=NotificationType.COMMUNITY_MESSAGE,
                    title="New comment on your post",
                    message="Someone commented on your community post.",
                    target_url="/community-posts",
                )

        return CommunityPostService._comment_to_response(saved_comment)

    @staticmethod
    def get_comments_by_post(
        db: Session,
        post_id: uuid.UUID,
    ) -> list[dict]:
        post = CommunityPostRepository.find_by_id(
            db=db,
            post_id=post_id,
        )

        if not post:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Community post not found",
            )

        comments = CommunityCommentRepository.find_by_post_id(
            db=db,
            post_id=post_id,
        )

        return [
            CommunityPostService._comment_to_response(comment)
            for comment in comments
        ]

    @staticmethod
    def delete_comment(
        db: Session,
        comment_id: uuid.UUID,
        current_user: AppUser,
    ) -> None:
        comment = CommunityCommentRepository.find_by_id(
            db=db,
            comment_id=comment_id,
        )

        if not comment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Community comment not found",
            )

        if comment.author_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete your own comment",
            )

        CommunityCommentRepository.soft_delete(
            db=db,
            comment=comment,
            deleted_by=current_user.id,
        )
