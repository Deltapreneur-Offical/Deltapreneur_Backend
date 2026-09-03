import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.entity.community.community_auction_bid import CommunityAuctionBid


class CommunityAuctionBidRepository:
    @staticmethod
    def _not_deleted_filter(query):
        return query.filter(CommunityAuctionBid.is_deleted.is_(False))

    @staticmethod
    def find_by_auction_id(
        db: Session,
        auction_id: uuid.UUID,
    ) -> list[CommunityAuctionBid]:
        query = (
            db.query(CommunityAuctionBid)
            .filter(CommunityAuctionBid.auction_id == auction_id)
            .order_by(CommunityAuctionBid.amount.desc())
        )
        return CommunityAuctionBidRepository._not_deleted_filter(query).all()

    @staticmethod
    def find_highest_bid(
        db: Session,
        auction_id: uuid.UUID,
    ) -> Optional[CommunityAuctionBid]:
        query = (
            db.query(CommunityAuctionBid)
            .filter(CommunityAuctionBid.auction_id == auction_id)
            .order_by(CommunityAuctionBid.amount.desc())
        )
        return CommunityAuctionBidRepository._not_deleted_filter(query).first()

    @staticmethod
    def find_by_bidder_id(
        db: Session,
        bidder_id: uuid.UUID,
    ) -> list[CommunityAuctionBid]:
        query = (
            db.query(CommunityAuctionBid)
            .filter(CommunityAuctionBid.bidder_id == bidder_id)
            .order_by(CommunityAuctionBid.created_at.desc())
        )
        return CommunityAuctionBidRepository._not_deleted_filter(query).all()

    @staticmethod
    def save(
        db: Session,
        bid: CommunityAuctionBid,
    ) -> CommunityAuctionBid:
        db.add(bid)
        db.commit()
        db.refresh(bid)

        return bid

    @staticmethod
    def mark_existing_bids_not_winning(
        db: Session,
        auction_id: uuid.UUID,
        *,
        commit: bool = True,
    ) -> None:
        bids = CommunityAuctionBidRepository.find_by_auction_id(
            db=db,
            auction_id=auction_id,
        )

        for bid in bids:
            bid.winning_bid = False

        if commit:
            db.commit()

    @staticmethod
    def soft_delete(
        db: Session,
        bid: CommunityAuctionBid,
        deleted_by: uuid.UUID,
    ) -> None:
        bid.is_deleted = True
        bid.deleted_at = datetime.now(timezone.utc)
        bid.deleted_by = deleted_by

        db.add(bid)
        db.commit()
