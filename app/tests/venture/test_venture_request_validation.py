"""Unit tests for venture request validation rules."""

import pytest
from pydantic import ValidationError

from app.model.venture.venture_request import (
    BrandDetailsRequest,
    ContactInfoRequest,
    CreateVentureRequest,
    GstinVerifyRequest,
    UpdateVentureRequest,
)
from app.utils.venture_enums import (
    VentureDealType,
    VentureStage,
)


def test_brand_name_rejects_whitespace_only() -> None:
    with pytest.raises(ValidationError):
        BrandDetailsRequest(brand_name="   ")


def test_website_must_be_http_https() -> None:
    with pytest.raises(ValidationError):
        BrandDetailsRequest(website="ftp://example.com")


def test_blank_website_becomes_none() -> None:
    brand = BrandDetailsRequest(website="")
    assert brand.website is None


def test_blank_phone_becomes_none() -> None:
    contact = ContactInfoRequest(phone_number="  ")
    assert contact.phone_number is None


def test_brand_details_accepts_currency() -> None:
    brand = BrandDetailsRequest(currency="SGD")
    assert brand.currency == "SGD"


def test_update_venture_request_accepts_currency() -> None:
    request = UpdateVentureRequest(currency="USD")
    assert request.currency == "USD"


def test_website_normalizes_host() -> None:
    brand = BrandDetailsRequest(website="HTTPS://Example.COM/path")
    assert brand.website == "https://example.com/path"


def test_contact_email_lowercased() -> None:
    contact = ContactInfoRequest(email="Founder@Example.COM")
    assert contact.email == "founder@example.com"


def test_contact_phone_e164() -> None:
    contact = ContactInfoRequest(phone_number="+919876543210")
    assert contact.phone_number == "+919876543210"


def test_contact_phone_accepts_ten_digit_indian() -> None:
    contact = ContactInfoRequest(phone_number="9876543210")
    assert contact.phone_number == "+919876543210"


def test_contact_phone_rejects_invalid() -> None:
    with pytest.raises(ValidationError):
        ContactInfoRequest(phone_number="19")


def test_gstin_pattern() -> None:
    req = GstinVerifyRequest(gstin="  22aaaaa0000a1z5  ")
    assert req.gstin == "22AAAAA0000A1Z5"


def test_gstin_rejects_invalid() -> None:
    with pytest.raises(ValidationError):
        GstinVerifyRequest(gstin="not-a-valid-gstin")


def test_current_problem_max_2000() -> None:
    with pytest.raises(ValidationError):
        CreateVentureRequest(current_problem="x" * 2001)


def test_auction_sale_type_rejected() -> None:
    with pytest.raises(ValidationError):
        CreateVentureRequest(
            sale_type="AUCTION",
            stage=VentureStage.REVENUE_GENERATING,
        )


def test_coerce_optional_text_preserves_str_enum() -> None:
    from app.service.venture import venture_service
    from app.utils.venture_enums import Industry, VentureType

    assert venture_service._coerce_optional_text(Industry.TECH) is Industry.TECH
    assert venture_service._coerce_optional_text(VentureType.FIFTY_FIFTY) is (
        VentureType.FIFTY_FIFTY
    )
    assert venture_service._coerce_optional_text("  ") is None
    assert venture_service._coerce_optional_text("hello") == "hello"


def test_regular_create_rejects_auction_sale_type() -> None:
    with pytest.raises(ValidationError):
        CreateVentureRequest(
            sale_type="AUCTION",
            deal_type=VentureDealType.FULL_ACQUISITION,
        )
