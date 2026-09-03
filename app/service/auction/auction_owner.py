"""Detect auction listers/owners who must not pay participation fees or bid."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.entity.auction.auction_participation_entity import AuctionParticipationType
from app.entity.community.community_auction import CommunityAuction
from app.repository.community_auction_repository import CommunityAuctionRepository
from app.repository.community_repository import CommunityRepository
from app.repository.software_auction_repository import SoftwareAuctionRepository
from app.repository.software_repository import SoftwareRepository
from app.repository.auction_repository import AuctionRepository
from app.repository.software_auction_repository import SoftwareAuctionRepository


class AuctionOwnerError(Exception):
    """Raised when the lister attempts participation or bidding on their own auction."""

    message = "You cannot participate in your own auction."


def is_community_auction_owner_sync(
    db: Session,
    auction_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    auction = CommunityAuctionRepository.find_by_id(db=db, auction_id=auction_id)
    if auction is None:
        return False
    community = CommunityRepository.find_by_id(db=db, community_id=auction.community_id)
    if community is not None and community.app_user_id == user_id:
        return True
    return auction.created_by == user_id


async def is_auction_owner(
    session: AsyncSession,
    auction_type: AuctionParticipationType,
    auction_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    if auction_type == AuctionParticipationType.COMMUNITY:
        result = await session.execute(
            select(CommunityAuction).where(CommunityAuction.id == auction_id)
        )
        auction = result.scalar_one_or_none()
        if auction is None:
            return False
        from app.entity.community.community import Community

        comm_result = await session.execute(
            select(Community).where(Community.id == auction.community_id)
        )
        community = comm_result.scalar_one_or_none()
        if community is not None and community.app_user_id == user_id:
            return True
        return auction.created_by == user_id

    if auction_type == AuctionParticipationType.SOFTWARE:
        repo = SoftwareAuctionRepository(session)
        auction = await repo.get_by_id(auction_id)
        if auction is None:
            return False
        software = await SoftwareRepository(session).get_by_id(auction.software_id)
        return software is not None and software.listed_by_user_id == user_id

    if auction_type == AuctionParticipationType.DOMAIN:
        repo = AuctionRepository(session)
        auction = await repo.get_auction_by_id(auction_id)
        if auction is None:
            return False
        return auction.created_by == user_id

    return False


def owner_participation_status() -> dict:
    """Participation payload for lister/owner (Java parity — no fee, no bid)."""
    return {
        "paid": True,
        "participationFeeInr": 0,
        "canBid": False,
        "isOwner": True,
    }
