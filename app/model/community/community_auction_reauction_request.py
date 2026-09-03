"""Re-auction body (frontend camelCase)."""

from __future__ import annotations

from decimal import Decimal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.entity.community.community_auction_duration import CommunityAuctionDuration


class CommunityAuctionReauctionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    min_bid_price: Decimal = Field(..., alias="minBidPrice", gt=0)
    duration: CommunityAuctionDuration
    creation_fee_order_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("creation_fee_order_id", "creationFeeOrderId"),
    )
