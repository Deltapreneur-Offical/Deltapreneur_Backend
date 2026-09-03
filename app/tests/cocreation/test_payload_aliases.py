from __future__ import annotations

from app.controller.cocreation.software_auction_controller import (
    ParticipationVerifyBody,
    SoftwareAuctionSettingsBody,
)
from app.model.cocreation.cocreation_request import CreateSoftwareRequest
from app.model.common.payment_request import RazorpayVerifyRequest
from app.model.community.community_auction_create_request import (
    CommunityAuctionCreateRequest,
)
from app.model.community.meeting_schedule_request import MeetingScheduleRequest
from app.utils.cocreation_enums import SoftwareAuctionDuration, SoftwarePurchaseType


def test_software_and_payment_payloads_accept_camel_and_snake_case():
    camel = ParticipationVerifyBody.model_validate(
        {
            "razorpayPaymentId": "pay_1",
            "razorpayOrderId": "order_1",
            "razorpaySignature": "sig_1",
        }
    )
    snake = ParticipationVerifyBody.model_validate(
        {
            "razorpay_payment_id": "pay_2",
            "razorpay_order_id": "order_2",
            "razorpay_signature": "sig_2",
        }
    )

    assert camel.razorpay_order_id == "order_1"
    assert snake.razorpay_payment_id == "pay_2"
    assert SoftwareAuctionSettingsBody.model_validate(
        {"participationFeeInr": 118}
    ).participation_fee_inr == 118
    assert SoftwareAuctionSettingsBody.model_validate(
        {"participation_fee_inr": 119}
    ).participation_fee_inr == 119
    assert RazorpayVerifyRequest.model_validate(
        {
            "razorpayPaymentId": "pay",
            "razorpayOrderId": "order",
            "razorpaySignature": "sig",
        }
    ).razorpay_signature == "sig"
    assert RazorpayVerifyRequest.model_validate(
        {
            "razorpay_payment_id": "pay",
            "razorpay_order_id": "order",
            "razorpay_signature": "sig",
        }
    ).razorpay_order_id == "order"


def test_technology_create_payload_accepts_camel_and_snake_case():
    camel = CreateSoftwareRequest.model_validate(
        {
            "name": "AI CRM",
            "purchaseType": "AUCTION",
            "minBidPrice": 5000,
            "auctionDuration": "SEVEN_DAYS",
            "auctionRationale": "Market discovery",
            "creationFeeOrderId": "order_test_creation_fee",
        }
    )
    snake = CreateSoftwareRequest.model_validate(
        {
            "name": "AI CRM",
            "purchase_type": SoftwarePurchaseType.AUCTION,
            "min_bid_price": 5000,
            "auction_duration": "SEVEN_DAYS",
            "auction_rationale": "Market discovery",
            "creation_fee_order_id": "order_test_creation_fee",
        }
    )

    assert camel.purchase_type == SoftwarePurchaseType.AUCTION
    assert camel.min_bid_price == 5000
    assert snake.auction_duration.value == "SEVEN_DAYS"


def test_software_auction_duration_includes_legacy_fifteen_days():
    assert SoftwareAuctionDuration.FIFTEEN_DAYS.to_days() == 15


def test_disruptor_payloads_accept_camel_and_snake_case():
    camel = CommunityAuctionCreateRequest.model_validate(
        {
            "communityId": "11111111-1111-1111-1111-111111111111",
            "duration": "SEVEN_DAYS",
            "minBidPrice": 500,
            "auctionTitle": "FastAPI Developer",
            "workType": "FREELANCE",
            "creationFeeOrderId": "order_test_creation_fee",
        }
    )
    snake = CommunityAuctionCreateRequest.model_validate(
        {
            "community_id": "11111111-1111-1111-1111-111111111111",
            "duration": "SEVEN_DAYS",
            "min_bid_price": 600,
            "auction_title": "FastAPI Developer",
            "work_type": "FREELANCE",
            "creation_fee_order_id": "order_test_creation_fee",
        }
    )
    meeting = MeetingScheduleRequest.model_validate(
        {
            "scheduled_at": "2026-06-01T10:00:00+05:30",
            "duration_minutes": 30,
            "topic": "Discovery",
        }
    )

    assert camel.min_bid_price == 500
    assert snake.min_bid_price == 600
    assert meeting.duration_minutes == 30
