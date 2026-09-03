import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.entity.community.community_post import CommunityPost


class CommunityPostRepository:
    @staticmethod
    def _not_deleted_filter(query):
        return query.filter(CommunityPost.is_deleted.is_(False))

    @staticmethod
    def find_all(db: Session) -> list[CommunityPost]:
        query = db.query(CommunityPost).order_by(
            CommunityPost.created_at.desc()
        )
        return CommunityPostRepository._not_deleted_filter(query).all()

    @staticmethod
    def find_by_id(
        db: Session,
        post_id: uuid.UUID,
    ) -> Optional[CommunityPost]:
        query = db.query(CommunityPost).filter(
            CommunityPost.id == post_id,
        )
        return CommunityPostRepository._not_deleted_filter(query).first()

    @staticmethod
    def find_by_community_id(
        db: Session,
        community_id: uuid.UUID,
    ) -> list[CommunityPost]:
        query = (
            db.query(CommunityPost)
            .filter(CommunityPost.community_id == community_id)
            .order_by(CommunityPost.created_at.desc())
        )
        return CommunityPostRepository._not_deleted_filter(query).all()

    @staticmethod
    def find_by_author_id(
        db: Session,
        author_id: uuid.UUID,
    ) -> list[CommunityPost]:
        query = (
            db.query(CommunityPost)
            .filter(CommunityPost.author_id == author_id)
            .order_by(CommunityPost.created_at.desc())
        )
        return CommunityPostRepository._not_deleted_filter(query).all()

    @staticmethod
    def save(
        db: Session,
        post: CommunityPost,
    ) -> CommunityPost:
        db.add(post)
        db.commit()
        db.refresh(post)

        return post

    @staticmethod
    def soft_delete(
        db: Session,
        post: CommunityPost,
        deleted_by: uuid.UUID,
    ) -> None:
        post.is_deleted = True
        post.deleted_at = datetime.now(timezone.utc)
        post.deleted_by = deleted_by

        db.add(post)
        db.commit()
