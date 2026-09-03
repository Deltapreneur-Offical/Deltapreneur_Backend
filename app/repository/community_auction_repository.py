import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from app.entity.community.community import Community
from app.entity.community.community_auction import CommunityAuction


class CommunityAuctionRepository:
    @staticmethod
    def _not_deleted_filter(query):
        return query.filter(CommunityAuction.is_deleted.is_(False))

    @staticmethod
    def find_all(db: Session) -> list[CommunityAuction]:
        query = db.query(CommunityAuction).order_by(
            CommunityAuction.created_at.desc()
        )
        return CommunityAuctionRepository._not_deleted_filter(query).all()

    @staticmethod
    def find_all_with_details(db: Session) -> list[CommunityAuction]:
        query = (
            db.query(CommunityAuction)
            .options(
                joinedload(CommunityAuction.community).joinedload(Community.app_user),
                joinedload(CommunityAuction.creator),
                joinedload(CommunityAuction.current_winner),
            )
            .order_by(CommunityAuction.created_at.desc())
        )
        return CommunityAuctionRepository._not_deleted_filter(query).all()

    @staticmethod
    def find_by_id(
        db: Session,
        auction_id: uuid.UUID,
    ) -> Optional[CommunityAuction]:
        query = db.query(CommunityAuction).filter(
            CommunityAuction.id == auction_id,
        )
        return CommunityAuctionRepository._not_deleted_filter(query).first()

    @staticmethod
    def find_by_id_for_update(
        db: Session,
        auction_id: uuid.UUID,
    ) -> Optional[CommunityAuction]:
        query = (
            db.query(CommunityAuction)
            .filter(CommunityAuction.id == auction_id)
            .with_for_update()
        )
        return CommunityAuctionRepository._not_deleted_filter(query).first()

    @staticmethod
    def find_by_community_id(
        db: Session,
        community_id: uuid.UUID,
    ) -> Optional[CommunityAuction]:
        query = (
            db.query(CommunityAuction)
            .filter(CommunityAuction.community_id == community_id)
            .order_by(CommunityAuction.created_at.desc())
        )
        return CommunityAuctionRepository._not_deleted_filter(query).first()

    @staticmethod
    def find_by_community_ids(
        db: Session,
        community_ids: list[uuid.UUID],
    ) -> list[CommunityAuction]:
        if not community_ids:
            return []
        query = (
            db.query(CommunityAuction)
            .filter(CommunityAuction.community_id.in_(community_ids))
            .order_by(CommunityAuction.created_at.desc())
        )
        return CommunityAuctionRepository._not_deleted_filter(query).all()

    @staticmethod
    def find_by_creator_id(
        db: Session,
        created_by: uuid.UUID,
    ) -> list[CommunityAuction]:
        query = (
            db.query(CommunityAuction)
            .filter(CommunityAuction.created_by == created_by)
            .order_by(CommunityAuction.created_at.desc())
        )
        return CommunityAuctionRepository._not_deleted_filter(query).all()

    @staticmethod
    def save(
        db: Session,
        auction: CommunityAuction,
    ) -> CommunityAuction:
        db.add(auction)
        db.commit()
        db.refresh(auction)

        return auction

    @staticmethod
    def find_expired_active(
        db: Session,
        now: datetime,
    ) -> list[CommunityAuction]:
        query = (
            db.query(CommunityAuction)
            .filter(
                CommunityAuction.end_time.isnot(None),
                CommunityAuction.end_time < now,
                CommunityAuction.status.in_(("ACTIVE", "EXTENDED")),
            )
            .order_by(CommunityAuction.end_time.asc())
        )
        return CommunityAuctionRepository._not_deleted_filter(query).all()

    @staticmethod
    def soft_delete(
        db: Session,
        auction: CommunityAuction,
        deleted_by: uuid.UUID,
    ) -> None:
        auction.is_deleted = True
        auction.deleted_at = datetime.now(timezone.utc)
        auction.deleted_by = deleted_by

        db.add(auction)
        db.commit()
