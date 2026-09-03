from datetime import datetime, timezone
from uuid import uuid4

from app.model.cocreation.cocreation_request import CreateSoftwareRequest
from app.model.cocreation.cocreation_response import SoftwareResponse
from app.utils.cocreation_enums import SoftwarePurchaseType, SoftwareStatus


def test_create_software_request_accepts_frontend_currency_field():
    payload = CreateSoftwareRequest.model_validate(
        {
            "name": "InvoiceFlow",
            "price": 4999,
            "purchaseType": "ONE_TIME",
            "currency": "INR",
            "agreement": {"terms": True},
        }
    )

    assert payload.currency == "INR"
    assert payload.purchase_type == SoftwarePurchaseType.ONE_TIME


def test_software_response_serializes_frontend_camel_case_fields():
    now = datetime.now(timezone.utc)
    response = SoftwareResponse(
        id=uuid4(),
        name="InvoiceFlow",
        video_link="https://example.com/demo",
        what_it_does="Creates invoices",
        how_it_helps="Saves time",
        github_link=None,
        image_url="https://example.com/logo.png",
        live_demo_link="https://example.com",
        tech_stack="React, FastAPI",
        price=4999,
        software_status=SoftwareStatus.AVAILABLE,
        purchase_type=SoftwarePurchaseType.ONE_TIME,
        status=True,
        views=3,
        official=False,
        featured=True,
        created_at=now,
        updated_at=now,
    )

    data = response.model_dump(mode="json", by_alias=True)

    assert data["videoLink"] == "https://example.com/demo"
    assert data["whatItDoes"] == "Creates invoices"
    assert data["howItHelps"] == "Saves time"
    assert data["imageUrl"] == "https://example.com/logo.png"
    assert data["liveDemoLink"] == "https://example.com"
    assert data["techStack"] == "React, FastAPI"
    assert data["softwareStatus"] == "AVAILABLE"
    assert data["purchaseType"] == "ONE_TIME"
    assert data["purchaseCount"] == 0
    assert data["createdAt"]
    assert data["updatedAt"]
