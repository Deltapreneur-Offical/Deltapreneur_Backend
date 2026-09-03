from decimal import Decimal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class CommunityAuctionBidRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    amount: Decimal = Field(gt=0)
    razorpay_order_id: str = Field(..., alias="razorpayOrderId")
    razorpay_payment_id: str = Field(..., alias="razorpayPaymentId")
    razorpay_signature: str = Field(..., alias="razorpaySignature")