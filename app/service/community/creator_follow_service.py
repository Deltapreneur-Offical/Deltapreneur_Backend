from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.entity.community.community import Community
from app.entity.community.creator_follow import CreatorFollow
from app.entity.notification.notification_type import NotificationType
from app.entity.user.app_user import AppUser
from app.repository.community_repository import CommunityRepository
from app.repository.creator_follow_repository import (
    CreatorFollowRepository,
    normalize_community_id,
)
from app.service.notification.notification_service import NotificationService

logger = logging.getLogger(__name__)


class CreatorFollowService:
    @staticmethod
    def _to_response(
        *,
        community_id: str | uuid.UUID,
        following: bool,
        follower_count: int,
    ) -> dict:
        normalized = normalize_community_id(community_id)
        return {
            "community_id": normalized,
            "communityId": normalized,
            "following": following,
            "follower_count": follower_count,
            "followerCount": follower_count,
            "count": follower_count,
        }

    @staticmethod
    def _get_community_or_404(db: Session, community_id: uuid.UUID) -> Community:
        community = CommunityRepository.find_by_id(db=db, community_id=community_id)
        if community is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Creator profile not found",
            )
        return community

    @staticmethod
    def _follower_label(user: AppUser) -> str:
        parts = [p for p in (user.firstname, user.lastname) if p]
        return " ".join(parts) if parts else (user.email or "Someone")

    @staticmethod
    def _notify_creator_on_follow(
        db: Session,
        *,
        community: Community,
        follower: AppUser,
    ) -> None:
        if community.app_user_id == follower.id:
            return
        owner = db.query(AppUser).filter(AppUser.id == community.app_user_id).first()
        if owner is None:
            return
        try:
            NotificationService.notify(
                db=db,
                user=owner,
                notification_type=NotificationType.COMMUNITY_PROFILE_UPDATED,
                title="New follower",
                message=f"{CreatorFollowService._follower_label(follower)} started following you.",
                target_url=f"/creator?id={community.id}",
            )
        except Exception:
            logger.exception("Creator follow saved but notification failed")

    @staticmethod
    def attach_follow_counts(
        db: Session,
        records: list[dict],
        *,
        id_key: str = "id",
        field: str = "followerCount",
    ) -> None:
        if not records:
            return
        community_ids = [
            record[id_key] for record in records if record.get(id_key) is not None
        ]
        if not community_ids:
            return
        counts = CreatorFollowRepository.bulk_counts(db, community_ids)
        for record in records:
            raw_id = record.get(id_key)
            if raw_id is None:
                continue
            record[field] = counts.get(normalize_community_id(raw_id), 0)

    @staticmethod
    def toggle_follow(
        db: Session,
        *,
        community_id: uuid.UUID,
        current_user: AppUser,
    ) -> dict:
        community = CreatorFollowService._get_community_or_404(db, community_id)
        if community.app_user_id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot follow your own profile",
            )

        existing = CreatorFollowRepository.find_active(
            db,
            follower_user_id=current_user.id,
            community_id=community_id,
        )
        if existing:
            CreatorFollowRepository.soft_delete(
                db,
                existing,
                deleted_by=current_user.id,
            )
            following = False
        else:
            prior = CreatorFollowRepository.find_any(
                db,
                follower_user_id=current_user.id,
                community_id=community_id,
            )
            if prior is not None:
                CreatorFollowRepository.restore(db, prior)
            else:
                CreatorFollowRepository.save(
                    db,
                    CreatorFollow(
                        follower_user_id=current_user.id,
                        community_id=community_id,
                    ),
                )
            following = True
            CreatorFollowService._notify_creator_on_follow(
                db,
                community=community,
                follower=current_user,
            )

        follower_count = CreatorFollowRepository.count_for_community(db, community_id)
        return CreatorFollowService._to_response(
            community_id=community_id,
            following=following,
            follower_count=follower_count,
        )

    @staticmethod
    def get_follow_status(
        db: Session,
        *,
        community_id: uuid.UUID,
        current_user: AppUser,
    ) -> dict:
        CreatorFollowService._get_community_or_404(db, community_id)
        following = (
            CreatorFollowRepository.find_active(
                db,
                follower_user_id=current_user.id,
                community_id=community_id,
            )
            is not None
        )
        follower_count = CreatorFollowRepository.count_for_community(db, community_id)
        return CreatorFollowService._to_response(
            community_id=community_id,
            following=following,
            follower_count=follower_count,
        )

    @staticmethod
    def get_bulk_status(
        db: Session,
        *,
        community_ids: list[str],
        current_user: AppUser,
    ) -> dict[str, dict]:
        if not community_ids:
            return {}
        counts = CreatorFollowRepository.bulk_counts(db, community_ids)
        followed = CreatorFollowRepository.followed_community_ids(
            db,
            follower_user_id=current_user.id,
            community_ids=community_ids,
        )
        result: dict[str, dict] = {}
        for raw_id in community_ids:
            key = normalize_community_id(raw_id)
            result[key] = {
                "following": key in followed,
                "count": counts.get(key, 0),
                "followerCount": counts.get(key, 0),
            }
        return result

    @staticmethod
    def get_bulk_counts(db: Session, *, community_ids: list[str]) -> dict[str, int]:
        if not community_ids:
            return {}
        counts = CreatorFollowRepository.bulk_counts(db, community_ids)
        return {
            normalize_community_id(raw_id): counts.get(normalize_community_id(raw_id), 0)
            for raw_id in community_ids
        }
