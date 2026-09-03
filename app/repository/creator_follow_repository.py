import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.entity.community.creator_follow import CreatorFollow


def normalize_community_id(community_id: str | uuid.UUID) -> str:
    return str(community_id or "").strip().lower()


class CreatorFollowRepository:
    @staticmethod
    def _active(query):
        return query.filter(CreatorFollow.is_deleted.is_(False))

    @staticmethod
    def find_active(
        db: Session,
        *,
        follower_user_id: uuid.UUID,
        community_id: str | uuid.UUID,
    ) -> Optional[CreatorFollow]:
        community_uuid = uuid.UUID(str(community_id))
        query = db.query(CreatorFollow).filter(
            CreatorFollow.follower_user_id == follower_user_id,
            CreatorFollow.community_id == community_uuid,
        )
        return CreatorFollowRepository._active(query).first()

    @staticmethod
    def find_any(
        db: Session,
        *,
        follower_user_id: uuid.UUID,
        community_id: str | uuid.UUID,
    ) -> Optional[CreatorFollow]:
        community_uuid = uuid.UUID(str(community_id))
        return (
            db.query(CreatorFollow)
            .filter(
                CreatorFollow.follower_user_id == follower_user_id,
                CreatorFollow.community_id == community_uuid,
            )
            .first()
        )

    @staticmethod
    def count_for_community(db: Session, community_id: str | uuid.UUID) -> int:
        community_uuid = uuid.UUID(str(community_id))
        query = db.query(CreatorFollow).filter(
            CreatorFollow.community_id == community_uuid,
        )
        return CreatorFollowRepository._active(query).count()

    @staticmethod
    def bulk_counts(db: Session, community_ids: list[str | uuid.UUID]) -> dict[str, int]:
        if not community_ids:
            return {}
        uuids = [uuid.UUID(str(cid)) for cid in community_ids]
        rows = (
            db.query(CreatorFollow.community_id, func.count(CreatorFollow.id))
            .filter(
                CreatorFollow.community_id.in_(uuids),
                CreatorFollow.is_deleted.is_(False),
            )
            .group_by(CreatorFollow.community_id)
            .all()
        )
        return {normalize_community_id(row[0]): int(row[1]) for row in rows}

    @staticmethod
    def followed_community_ids(
        db: Session,
        *,
        follower_user_id: uuid.UUID,
        community_ids: list[str | uuid.UUID],
    ) -> set[str]:
        if not community_ids:
            return set()
        uuids = [uuid.UUID(str(cid)) for cid in community_ids]
        rows = (
            db.query(CreatorFollow.community_id)
            .filter(
                CreatorFollow.follower_user_id == follower_user_id,
                CreatorFollow.community_id.in_(uuids),
                CreatorFollow.is_deleted.is_(False),
            )
            .all()
        )
        return {normalize_community_id(row[0]) for row in rows}

    @staticmethod
    def save(db: Session, follow: CreatorFollow) -> CreatorFollow:
        db.add(follow)
        db.commit()
        db.refresh(follow)
        return follow

    @staticmethod
    def soft_delete(
        db: Session,
        follow: CreatorFollow,
        *,
        deleted_by: uuid.UUID,
    ) -> None:
        follow.is_deleted = True
        follow.deleted_at = datetime.now(timezone.utc)
        follow.deleted_by = deleted_by
        db.add(follow)
        db.commit()

    @staticmethod
    def restore(db: Session, follow: CreatorFollow) -> CreatorFollow:
        follow.is_deleted = False
        follow.deleted_at = None
        follow.deleted_by = None
        db.add(follow)
        db.commit()
        db.refresh(follow)
        return follow
