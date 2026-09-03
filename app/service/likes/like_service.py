import logging
import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.entity.cobranding.domain_listing_entity import DomainListing
from app.entity.cocreation.software_entity import Software
from app.entity.coventure.venture_entity import Venture
from app.entity.likes.like import Like
from app.entity.likes.like_type import LikeType
from app.entity.notification.notification_type import NotificationType
from app.entity.user.app_user import AppUser
from app.entity.virtual_assistant.virtual_assistant_entity import VirtualAssistantApplication
from app.repository.like_repository import LikeRepository
from app.service.notification.notification_service import NotificationService


class LikeService:
    @staticmethod
    def normalize_entity_id(entity_id: str) -> str:
        return str(entity_id or "").strip().lower()

    @staticmethod
    def _validate_like_type(like_type: str) -> str:
        try:
            return LikeType(like_type.upper()).value
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid like type",
            ) from None

    @staticmethod
    def _to_response(
        *,
        like_type: str,
        entity_id: str,
        liked: bool,
        total_likes: int,
    ) -> dict:
        return {
            "type": like_type,
            "entity_id": LikeService.normalize_entity_id(entity_id),
            "liked": liked,
            "total_likes": total_likes,
            "count": total_likes,
        }

    @staticmethod
    def attach_like_counts(
        db: Session,
        like_type: str,
        records: list[dict],
        *,
        id_key: str = "id",
        field: str = "likeCount",
    ) -> None:
        if not records:
            return
        normalized_type = LikeService._validate_like_type(like_type)
        entity_ids = [
            LikeService.normalize_entity_id(record[id_key])
            for record in records
            if record.get(id_key) is not None
        ]
        if not entity_ids:
            return
        counts = LikeService.get_bulk_counts(db, normalized_type, entity_ids)
        for record in records:
            raw_id = record.get(id_key)
            if raw_id is None:
                continue
            record[field] = counts.get(LikeService.normalize_entity_id(raw_id), 0)

    @staticmethod
    def _liker_label(user: AppUser) -> str:
        parts = [p for p in (user.firstname, user.lastname) if p]
        return " ".join(parts) if parts else (user.email or "Someone")

    @staticmethod
    def _notify_owner_on_like(
        db: Session,
        like_type: str,
        entity_id: str,
        liker: AppUser,
    ) -> None:
        try:
            entity_uuid = uuid.UUID(str(entity_id))
        except ValueError:
            return

        owner_id: Optional[uuid.UUID] = None
        title = "Your listing was liked"
        message = f"{LikeService._liker_label(liker)} liked your listing."
        target_url: Optional[str] = None

        try:
            if like_type == LikeType.DOMAIN.value:
                listing = (
                    db.query(DomainListing)
                    .filter(DomainListing.id == entity_uuid, DomainListing.is_deleted.is_(False))
                    .first()
                )
                if listing is None:
                    return
                owner_id = listing.listed_by_user_id
                label = f"{listing.domain_name}{listing.domain_extension}".strip()
                message = f"{LikeService._liker_label(liker)} liked {label}."
                target_url = f"/domains?id={entity_id}"
            elif like_type == LikeType.VENTURE.value:
                venture = (
                    db.query(Venture)
                    .filter(Venture.id == entity_uuid, Venture.is_deleted.is_(False))
                    .first()
                )
                if venture is None:
                    return
                owner_id = venture.listed_by_user_id
                brand = getattr(venture, "brand_details", None)
                name = getattr(brand, "brand_name", None) if brand else None
                message = f"{LikeService._liker_label(liker)} liked {name or 'your venture'}."
                target_url = f"/ventures?id={entity_id}"
            elif like_type == LikeType.SOFTWARE.value:
                software = (
                    db.query(Software)
                    .filter(Software.id == entity_uuid, Software.is_deleted.is_(False))
                    .first()
                )
                if software is None:
                    return
                owner_id = software.listed_by_user_id
                message = f"{LikeService._liker_label(liker)} liked {software.name}."
                target_url = f"/technology?id={entity_id}"
            elif like_type == LikeType.VIRTUAL_ASSISTANT.value:
                application = (
                    db.query(VirtualAssistantApplication)
                    .filter(
                        VirtualAssistantApplication.id == entity_uuid,
                        VirtualAssistantApplication.is_deleted.is_(False),
                    )
                    .first()
                )
                if application is None or not application.user_id:
                    return
                try:
                    owner_id = uuid.UUID(str(application.user_id))
                except ValueError:
                    return
                message = (
                    f"{LikeService._liker_label(liker)} liked "
                    f"{application.full_name or 'your Virtual Assistant profile'}."
                )
                target_url = f"/operations?section=assistance&id={entity_id}"
            else:
                return

            if owner_id is None or owner_id == liker.id:
                return

            owner = db.query(AppUser).filter(AppUser.id == owner_id).first()
            if owner is None:
                return
        except (SQLAlchemyError, AttributeError, TypeError, ValueError):
            logging.getLogger(__name__).warning(
                "Like notification skipped for %s/%s because the related lookup failed",
                like_type,
                entity_id,
                exc_info=True,
            )
            return

        try:
            NotificationService.notify(
                db=db,
                user=owner,
                notification_type=NotificationType.LISTING_LIKED,
                title=title,
                message=message,
                target_url=target_url,
            )
        except Exception:
            pass

    @staticmethod
    def toggle_like(        db: Session,
        like_type: str,
        entity_id: str,
        current_user: AppUser,
    ) -> dict:
        normalized_type = LikeService._validate_like_type(like_type)

        existing_like = LikeRepository.find_by_user_type_entity(
            db=db,
            user_id=current_user.id,
            like_type=normalized_type,
            entity_id=entity_id,
        )

        if existing_like:
            LikeRepository.soft_delete(
                db=db,
                like=existing_like,
                deleted_by=current_user.id,
            )
            liked = False
        else:
            prior_like = LikeRepository.find_any_by_user_type_entity(
                db=db,
                user_id=current_user.id,
                like_type=normalized_type,
                entity_id=entity_id,
            )
            if prior_like is not None:
                LikeRepository.restore(db=db, like=prior_like)
            else:
                like = Like(
                    user_id=current_user.id,
                    like_type=normalized_type,
                    entity_id=LikeService.normalize_entity_id(entity_id),
                )
                LikeRepository.save(
                    db=db,
                    like=like,
                )
            liked = True

        total_likes = LikeRepository.count_by_type_entity(
            db=db,
            like_type=normalized_type,
            entity_id=entity_id,
        )

        if liked:
            LikeService._notify_owner_on_like(
                db, normalized_type, entity_id, current_user
            )

        return LikeService._to_response(
            like_type=normalized_type,
            entity_id=entity_id,
            liked=liked,
            total_likes=total_likes,
        )

    @staticmethod
    def get_like_status(
        db: Session,
        like_type: str,
        entity_id: str,
        current_user: AppUser,
    ) -> dict:
        normalized_type = LikeService._validate_like_type(like_type)

        liked = LikeRepository.exists_by_user_type_entity(
            db=db,
            user_id=current_user.id,
            like_type=normalized_type,
            entity_id=entity_id,
        )

        total_likes = LikeRepository.count_by_type_entity(
            db=db,
            like_type=normalized_type,
            entity_id=entity_id,
        )

        return LikeService._to_response(
            like_type=normalized_type,
            entity_id=entity_id,
            liked=liked,
            total_likes=total_likes,
        )

    @staticmethod
    def get_my_liked_entity_ids(
        db: Session,
        like_type: str,
        current_user: AppUser,
    ) -> dict:
        normalized_type = LikeService._validate_like_type(like_type)

        entity_ids = LikeRepository.find_entity_ids_by_user_and_type(
            db=db,
            user_id=current_user.id,
            like_type=normalized_type,
        )

        return {
            "type": normalized_type,
            "entity_ids": entity_ids,
        }

    @staticmethod
    def get_users_who_liked(
        db: Session,
        like_type: str,
        entity_id: str,
    ) -> dict:
        normalized_type = LikeService._validate_like_type(like_type)

        likes = LikeRepository.find_by_type_entity(
            db=db,
            like_type=normalized_type,
            entity_id=entity_id,
        )

        users = []
        for like in likes:
            user = like.user
            users.append(
                {
                    "user_id": str(like.user_id),
                    "email": user.email if user else None,
                    "firstname": getattr(user, "firstname", None) if user else None,
                    "lastname": getattr(user, "lastname", None) if user else None,
                }
            )

        return {
            "type": normalized_type,
            "entity_id": entity_id,
            "total_likes": len(users),
            "users": users,
        }

    @staticmethod
    def get_bulk_counts(
        db: Session,
        like_type: str,
        entity_ids: list[str],
    ) -> dict[str, int]:
        normalized_type = LikeService._validate_like_type(like_type)
        counts = LikeRepository.bulk_count_by_entities(
            db=db,
            like_type=normalized_type,
            entity_ids=entity_ids,
        )
        result: dict[str, int] = {}
        for entity_id in entity_ids:
            if not entity_id:
                continue
            key = LikeService.normalize_entity_id(entity_id)
            result[key] = counts.get(key, 0)
        return result

    @staticmethod
    def get_bulk_status(
        db: Session,
        like_type: str,
        entity_ids: list[str],
        current_user: AppUser,
    ) -> dict:
        normalized_type = LikeService._validate_like_type(like_type)
        counts = LikeRepository.bulk_count_by_entities(
            db=db,
            like_type=normalized_type,
            entity_ids=entity_ids,
        )
        liked_ids = LikeRepository.find_liked_entity_ids_for_user(
            db=db,
            user_id=current_user.id,
            like_type=normalized_type,
            entity_ids=entity_ids,
        )
        result: dict[str, dict] = {}

        for entity_id in entity_ids:
            if not entity_id:
                continue
            key = str(entity_id)
            normalized = LikeService.normalize_entity_id(entity_id)
            total_likes = counts.get(normalized, 0)
            result[key] = {
                "liked": normalized in liked_ids,
                "count": total_likes,
                "total_likes": total_likes,
            }

        return result
