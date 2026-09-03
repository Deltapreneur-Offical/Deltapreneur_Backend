import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.entity.community.community_comment import CommunityComment


class CommunityCommentRepository:
    @staticmethod
    def _not_deleted_filter(query):
        return query.filter(CommunityComment.is_deleted.is_(False))

    @staticmethod
    def find_by_id(
        db: Session,
        comment_id: uuid.UUID,
    ) -> Optional[CommunityComment]:
        query = db.query(CommunityComment).filter(
            CommunityComment.id == comment_id,
        )
        return CommunityCommentRepository._not_deleted_filter(query).first()

    @staticmethod
    def find_by_post_id(
        db: Session,
        post_id: uuid.UUID,
    ) -> list[CommunityComment]:
        query = (
            db.query(CommunityComment)
            .filter(CommunityComment.post_id == post_id)
            .order_by(CommunityComment.created_at.asc())
        )
        return CommunityCommentRepository._not_deleted_filter(query).all()

    @staticmethod
    def find_by_author_id(
        db: Session,
        author_id: uuid.UUID,
    ) -> list[CommunityComment]:
        query = (
            db.query(CommunityComment)
            .filter(CommunityComment.author_id == author_id)
            .order_by(CommunityComment.created_at.desc())
        )
        return CommunityCommentRepository._not_deleted_filter(query).all()

    @staticmethod
    def save(
        db: Session,
        comment: CommunityComment,
    ) -> CommunityComment:
        db.add(comment)
        db.commit()
        db.refresh(comment)

        return comment

    @staticmethod
    def soft_delete(
        db: Session,
        comment: CommunityComment,
        deleted_by: uuid.UUID,
    ) -> None:
        comment.is_deleted = True
        comment.deleted_at = datetime.now(timezone.utc)
        comment.deleted_by = deleted_by

        db.add(comment)
        db.commit()
