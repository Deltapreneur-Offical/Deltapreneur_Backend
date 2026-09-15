"""Hardware listings must never expose GitHub URLs to buyers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.model.cocreation.purchase_mapper import build_purchase_response
from app.model.cocreation.software_mapper import build_software_response
from app.service.cocreation.cocreation_payment_service import buyer_delivery_github
from app.utils.cocreation_enums import (
    SoftwarePaymentStatus,
    SoftwarePurchaseCompletionStatus,
    SoftwarePurchaseType,
    SoftwareStatus,
    TechnologyType,
)


def _software(*, technology_type: TechnologyType, github_link: str | None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Listing",
        description=None,
        video_link=None,
        what_it_does=None,
        how_it_helps=None,
        github_link=github_link,
        documentation_urls=None,
        download_urls=None,
        image_url=None,
        live_demo_link=None,
        tech_stack=None,
        technology_type=technology_type,
        category=None,
        pricing_demand=None,
        price=100.0,
        seller_price=85.0,
        currency="INR",
        pricing_plans=None,
        software_status=SoftwareStatus.AVAILABLE,
        purchase_type=SoftwarePurchaseType.ONE_TIME,
        status=True,
        views=0,
        official=False,
        featured=False,
        verified=True,
        verified_at=None,
        rejected=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        agreement=None,
        listed_by=None,
    )


def _purchase(software, *, delivered_github: str | None = None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        software_id=software.id,
        buyer_id=uuid.uuid4(),
        buyer_full_name="Buyer",
        buyer_email="buyer@test.local",
        buyer_phone="9999999999",
        payment_status=SoftwarePaymentStatus.COMPLETED,
        completion_status=SoftwarePurchaseCompletionStatus.CONFIRMED,
        selected_plan=None,
        expiry_date=None,
        co_brother_opt_in=False,
        co_brother_help_paid=False,
        gross_amount_inr=100.0,
        sold_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        delivered_github_link=delivered_github,
        delivered_documentation_urls=None,
        delivered_download_urls=None,
        software=software,
    )


def test_software_with_github_shown_to_buyer():
    software = _software(
        technology_type=TechnologyType.SOFTWARE,
        github_link="https://github.com/org/repo",
    )
    purchase = _purchase(software)
    payload = build_purchase_response(purchase)
    assert payload["software"]["githubLink"] == "https://github.com/org/repo"
    assert (
        buyer_delivery_github(purchase, software) == "https://github.com/org/repo"
    )


def test_software_without_github_hidden_from_buyer():
    software = _software(technology_type=TechnologyType.SOFTWARE, github_link=None)
    purchase = _purchase(software)
    payload = build_purchase_response(purchase)
    assert payload["software"]["githubLink"] in (None, "")
    assert buyer_delivery_github(purchase, software) == ""


def test_hardware_with_github_hidden_from_buyer():
    software = _software(
        technology_type=TechnologyType.HARDWARE,
        github_link="https://github.com/org/hardware-secret",
    )
    purchase = _purchase(
        software,
        delivered_github="https://github.com/org/hardware-secret",
    )
    payload = build_purchase_response(purchase)
    assert payload["software"]["githubLink"] is None
    assert buyer_delivery_github(purchase, software) == ""

    detail = build_software_response(
        software,
        viewer_purchase=purchase,
        is_owner=False,
        hide_github_from_public=True,
    )
    assert detail.github_link is None


def test_hardware_without_github_hidden_from_buyer():
    software = _software(technology_type=TechnologyType.HARDWARE, github_link=None)
    purchase = _purchase(software)
    payload = build_purchase_response(purchase)
    assert payload["software"]["githubLink"] is None
    assert buyer_delivery_github(purchase, software) == ""


def test_hardware_owner_can_still_see_github_on_listing():
    software = _software(
        technology_type=TechnologyType.HARDWARE,
        github_link="https://github.com/org/hardware-secret",
    )
    detail = build_software_response(
        software,
        is_owner=True,
        hide_github_from_public=True,
    )
    assert detail.github_link == "https://github.com/org/hardware-secret"
