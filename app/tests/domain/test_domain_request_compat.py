import pytest

from app.model.domain.domain_request import CreateDomainRequest, UpdateDomainRequest


def test_create_domain_request_accepts_frontend_shape() -> None:
    req = CreateDomainRequest(
        domainName="mybrand",
        domainExtension=".com",
        pricingDemand="NEGOTIABLE",
        askingPrice=120000,
        saleType="ONE_TIME",
        contactInfo={"email": "owner@test.local"},
    )
    assert req.domain_name == "mybrand.com"
    assert req.description == "NEGOTIABLE"


def test_create_domain_request_accepts_snake_case_shape() -> None:
    req = CreateDomainRequest(
        domain_name="mybrand.org",
        description="FIXED_PRICE",
    )
    assert req.domain_name == "mybrand.org"
    assert req.description == "FIXED_PRICE"


def test_update_domain_request_accepts_extension_and_pricing_alias() -> None:
    req = UpdateDomainRequest(
        domainName="nextbrand",
        domainExtension="io",
        pricingDemand="NEGOTIABLE",
    )
    assert req.domain_name == "nextbrand.io"
    assert req.description == "NEGOTIABLE"


def test_update_domain_request_requires_any_supported_field() -> None:
    with pytest.raises(Exception):
        UpdateDomainRequest(agreement={"terms": True})
