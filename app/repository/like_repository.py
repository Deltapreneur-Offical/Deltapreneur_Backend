import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.entity.likes.like import Like


def normalize_entity_id(entity_id: str) -> str:
    return str(entity_id or "").strip().lower()


class LikeRepository:
    @staticmethod
    def _not_deleted_filter(query):
        return query.filter(Like.is_deleted.is_(False))

    @staticmethod
    def _entity_id_filter(query, entity_id: str):
        return query.filter(
            func.lower(Like.entity_id) == normalize_entity_id(entity_id),
        )

    @staticmethod
    def find_by_user_type_entity(
        db: Session,
        user_id: uuid.UUID,
        like_type: str,
        entity_id: str,
    ) -> Optional[Like]:
        query = db.query(Like).filter(
            Like.user_id == user_id,
            Like.like_type == like_type,
        )
        query = LikeRepository._entity_id_filter(query, entity_id)
        return LikeRepository._not_deleted_filter(query).first()

    @staticmethod
    def find_any_by_user_type_entity(
        db: Session,
        user_id: uuid.UUID,
        like_type: str,
        entity_id: str,
    ) -> Optional[Like]:
        query = db.query(Like).filter(
            Like.user_id == user_id,
            Like.like_type == like_type,
        )
        return LikeRepository._entity_id_filter(query, entity_id).first()

    @staticmethod
    def count_by_type_entity(
        db: Session,
        like_type: str,
        entity_id: str,
    ) -> int:
        query = db.query(Like).filter(Like.like_type == like_type)
        query = LikeRepository._entity_id_filter(query, entity_id)
        return LikeRepository._not_deleted_filter(query).count()

    @staticmethod
    def bulk_count_by_entities(
        db: Session,
        like_type: str,
        entity_ids: list[str],
    ) -> dict[str, int]:
        normalized = [
            normalize_entity_id(entity_id)
            for entity_id in entity_ids
            if entity_id
        ]
        if not normalized:
            return {}

        rows = (
            db.query(func.lower(Like.entity_id), func.count(Like.id))
            .filter(
                Like.like_type == like_type,
                func.lower(Like.entity_id).in_(normalized),
                Like.is_deleted.is_(False),
            )
            .group_by(func.lower(Like.entity_id))
            .all()
        )
        return {row[0]: int(row[1]) for row in rows}

    @staticmethod
    def find_liked_entity_ids_for_user(
        db: Session,
        user_id: uuid.UUID,
        like_type: str,
        entity_ids: list[str],
    ) -> set[str]:
        normalized = [
            normalize_entity_id(entity_id)
            for entity_id in entity_ids
            if entity_id
        ]
        if not normalized:
            return set()

        rows = (
            db.query(func.lower(Like.entity_id))
            .filter(
                Like.user_id == user_id,
                Like.like_type == like_type,
                func.lower(Like.entity_id).in_(normalized),
                Like.is_deleted.is_(False),
            )
            .all()
        )
        return {row[0] for row in rows}

    @staticmethod
    def exists_by_user_type_entity(
        db: Session,
        user_id: uuid.UUID,
        like_type: str,
        entity_id: str,
    ) -> bool:
        return (
            LikeRepository.find_by_user_type_entity(
                db=db,
                user_id=user_id,
                like_type=like_type,
                entity_id=entity_id,
            )
            is not None
        )

    @staticmethod
    def find_entity_ids_by_user_and_type(
        db: Session,
        user_id: uuid.UUID,
        like_type: str,
    ) -> list[str]:
        query = db.query(Like).filter(
            Like.user_id == user_id,
            Like.like_type == like_type,
        )
        likes = LikeRepository._not_deleted_filter(query).all()

        return [like.entity_id for like in likes]

    @staticmethod
    def find_by_type_entity(
        db: Session,
        like_type: str,
        entity_id: str,
    ) -> list[Like]:
        query = db.query(Like).filter(Like.like_type == like_type)
        query = LikeRepository._entity_id_filter(query, entity_id).order_by(
            Like.created_at.desc(),
        )

        return LikeRepository._not_deleted_filter(query).all()

    @staticmethod
    def save(
        db: Session,
        like: Like,
    ) -> Like:
        db.add(like)
        db.commit()
        db.refresh(like)
        return like

    @staticmethod
    def soft_delete(
        db: Session,
        like: Like,
        deleted_by: uuid.UUID,
    ) -> None:
        like.is_deleted = True
        like.deleted_at = datetime.now(timezone.utc)
        like.deleted_by = deleted_by

        db.add(like)
        db.commit()

    @staticmethod
    def restore(
        db: Session,
        like: Like,
    ) -> Like:
        like.is_deleted = False
        like.deleted_at = None
        like.deleted_by = None

        db.add(like)
        db.commit()
        db.refresh(like)
        return like
