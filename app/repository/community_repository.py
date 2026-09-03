import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.entity.community.community import Community


class CommunityRepository:
    @staticmethod
    def _not_deleted_filter(query):
        return query.filter(Community.is_deleted.is_(False))

    @staticmethod
    def find_all(db: Session) -> list[Community]:
        query = db.query(Community).order_by(Community.created_at.desc())
        return CommunityRepository._not_deleted_filter(query).all()

    @staticmethod
    def find_for_listing(
        db: Session,
        *,
        featured_only: bool = False,
        limit: int | None = None,
    ) -> list[Community]:
        query = db.query(Community).order_by(
            Community.featured.desc(),
            Community.created_at.desc(),
        )
        query = CommunityRepository._not_deleted_filter(query)
        if featured_only:
            query = query.filter(Community.featured.is_(True))
        if limit is not None:
            query = query.limit(limit)
        return query.all()

    @staticmethod
    def find_by_id(
        db: Session,
        community_id: uuid.UUID,
    ) -> Optional[Community]:
        query = db.query(Community).filter(
            Community.id == community_id,
        )
        return CommunityRepository._not_deleted_filter(query).first()

    @staticmethod
    def find_by_id_any(
        db: Session,
        community_id: uuid.UUID,
    ) -> Optional[Community]:
        return (
            db.query(Community)
            .filter(Community.id == community_id)
            .first()
        )

    @staticmethod
    def find_by_app_user_id(
        db: Session,
        app_user_id: uuid.UUID,
    ) -> Optional[Community]:
        query = db.query(Community).filter(
            Community.app_user_id == app_user_id,
        )
        return CommunityRepository._not_deleted_filter(query).first()

    @staticmethod
    def find_all_by_app_user_id(
        db: Session,
        app_user_id: uuid.UUID,
    ) -> list[Community]:
        return (
            db.query(Community)
            .filter(Community.app_user_id == app_user_id)
            .order_by(
                Community.is_deleted.asc(),
                Community.updated_at.desc(),
            )
            .all()
        )

    @staticmethod
    def find_any_by_app_user_id(
        db: Session,
        app_user_id: uuid.UUID,
    ) -> Optional[Community]:
        return (
            db.query(Community)
            .filter(Community.app_user_id == app_user_id)
            .first()
        )

    @staticmethod
    def find_by_linked_in_id(
        db: Session,
        linked_in_id: str,
    ) -> Optional[Community]:
        query = db.query(Community).filter(
            Community.linked_in_id == linked_in_id,
        )
        return CommunityRepository._not_deleted_filter(query).first()

    @staticmethod
    def save(
        db: Session,
        community: Community,
    ) -> Community:
        db.add(community)
        db.commit()
        db.refresh(community)

        return community

    @staticmethod
    def soft_delete(
        db: Session,
        community: Community,
        deleted_by: uuid.UUID,
    ) -> None:
        community.is_deleted = True
        community.deleted_at = datetime.now(timezone.utc)
        community.deleted_by = deleted_by

        db.add(community)
        db.commit()

    @staticmethod
    def clear_linked_in_id_from_other_users(
        db: Session,
        linked_in_id: str,
        exclude_app_user_id: uuid.UUID,
    ) -> None:
        other_communities = (
            db.query(Community)
            .filter(
                Community.linked_in_id == linked_in_id,
                Community.app_user_id != exclude_app_user_id,
            )
            .all()
        )
        for other in other_communities:
            other.linked_in_id = None
            db.add(other)
        db.flush()
