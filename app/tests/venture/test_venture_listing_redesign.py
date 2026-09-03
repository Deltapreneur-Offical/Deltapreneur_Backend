"""Tests for venture listing redesign validation and bid rules."""

import pytest
from pydantic import ValidationError

from app.model.venture.venture_request import (
    CoVentureApplyRequest,
    CompanyProfileRequest,
    CreateVentureRequest,
    TeamMemberRequest,
    VentureRoleRequest,
)
from app.utils.venture_enums import VentureListingMode


def test_venture_create_requires_ownership_liquidation_percent() -> None:
    with pytest.raises(ValidationError):
        CreateVentureRequest(
            listing_mode=VentureListingMode.VENTURE,
            equity_percent_offered=None,
        )


def test_venture_create_accepts_ownership_liquidation_percent() -> None:
    req = CreateVentureRequest(
        listing_mode=VentureListingMode.VENTURE,
        equity_percent_offered=25.5,
    )
    assert req.equity_percent_offered == 25.5
    assert req.acquisition_flow.value == "SELLER_SELECTS"


def test_company_profile_revenue_history_fields() -> None:
    profile = CompanyProfileRequest(
        current_year_revenue_inr=1000000,
        previous_year_revenue_inr=750000,
        two_years_ago_revenue_inr=500000,
    )
    assert profile.current_year_revenue_inr == 1000000
    assert profile.previous_year_revenue_inr == 750000
    assert profile.two_years_ago_revenue_inr == 500000


def test_team_member_validation() -> None:
    member = TeamMemberRequest(
        name="Ada Lovelace",
        role="CTO",
        equity_percent=12.5,
        linkedin_url="https://linkedin.com/in/ada",
    )
    assert member.equity_percent == 12.5


def test_coventure_role_requires_role_offer_and_equity() -> None:
    with pytest.raises(ValidationError):
        CreateVentureRequest(
            listing_mode=VentureListingMode.CO_VENTURE,
            roles=[VentureRoleRequest(title="", equity_offer=10, investment_seeking=1000)],
        )


def test_coventure_role_requires_investment_seeking() -> None:
    with pytest.raises(ValidationError):
        CreateVentureRequest(
            listing_mode=VentureListingMode.CO_VENTURE,
            roles=[VentureRoleRequest(
                role_offer="Technical Co-founder",
                equity_offer=15,
            )],
        )


def test_coventure_role_accepts_new_fields() -> None:
    req = CreateVentureRequest(
        listing_mode=VentureListingMode.CO_VENTURE,
        roles=[VentureRoleRequest(
            role_offer="Technical Co-founder",
            equity_offer=15,
            investment_seeking=250000,
        )],
    )
    assert req.roles[0].role_offer == "Technical Co-founder"
    assert req.roles[0].equity_offer == 15
    assert req.roles[0].investment_seeking == 250000


def test_coventure_apply_accepts_video_introduction_url() -> None:
    req = CoVentureApplyRequest(
        fullName="Partner One",
        phone="9876543210",
        description="I am a strong fit.",
        videoIntroductionUrl="https://www.youtube.com/watch?v=example",
    )
    assert req.video_introduction_url == "https://www.youtube.com/watch?v=example"


def test_verification_video_url_normalized() -> None:
    req = CreateVentureRequest(
        listing_mode=VentureListingMode.VENTURE,
        equity_percent_offered=10,
        verification_requested=True,
        verification_video_url="https://youtu.be/demo",
    )
    assert req.verification_requested is True
    assert req.verification_video_url == "https://youtu.be/demo"
