"""Tests for ResellPortal product mapper."""
from app.service.resellportal.product_mapper import (
    PRODUCT_KEY_MAP,
    PARAM_BUILDERS,
    build_order_parameters,
    derive_cpanel_username,
    get_mapped_services,
    get_product_key,
    is_provider_mapped,
    validate_order_input,
)


def test_product_key_map_contains_all_confirmed_services():
    confirmed = [
        "ai-business-suite",
        "website-builder",
        "web-hosting",
        "cloud-storage",
        "email-marketing",
        "esim",
        "smm-growth",
        "vpn",
        "crm",
        "invoice-ai",
        "appointment-booking",
        "document-signer",
        "business-phone",
        "social-media-automation",
        "reputation-management",
        "link-in-bio",
    ]
    for slug in confirmed:
        assert get_product_key(slug) is not None, f"Missing product_key for {slug}"
        assert is_provider_mapped(slug) is True


def test_product_key_map_excludes_unavailable_services():
    assert get_product_key("wordpress-plugin-pack") is None
    assert is_provider_mapped("wordpress-plugin-pack") is False


def test_build_ai_business_tools_params():
    params = build_order_parameters("ai_business_tools", "pro", "monthly")
    assert params == {"ai_tools": ["content-marketing-suite"]}


def test_build_cloud_storage_params_with_metadata():
    params = build_order_parameters("cloud_storage", "starter", "monthly", {"storagePlan": "200gb"})
    assert params == {"storage_plan": "200gb"}


def test_build_cloud_storage_params_fallback():
    params = build_order_parameters("cloud_storage", "starter", "monthly")
    assert params == {"storage_plan": "100gb"}


def test_build_cloud_storage_params_invalid_fallback():
    params = build_order_parameters("cloud_storage", "starter", "monthly", {"storagePlan": "invalid"})
    assert params == {"storage_plan": "100gb"}


def test_build_esim_params():
    params = build_order_parameters("esim", "starter", "monthly", {"packageCode": "global-5gb"})
    assert params == {"package_code": "global-5gb"}


def test_build_smm_params():
    params = build_order_parameters(
        "smm",
        "starter",
        "monthly",
        {"serviceId": "insta-likes", "link": "https://example.com", "quantity": 500},
    )
    assert params == {"service_id": "insta-likes", "link": "https://example.com", "quantity": 500}


def test_build_vpn_params():
    params = build_order_parameters("vpn", "pro", "monthly", {"serverId": "us-east-1", "portId": "443"})
    assert params == {"server_id": "us-east-1", "port_id": "443"}


def test_build_web_hosting_params():
    params = build_order_parameters("web_hosting", "starter", "monthly", {
        "cpanelUsername": "cobrother",
        "primaryDomain": "cobrother.com",
    })
    assert params == {"cpanel_username": "cobrother", "primary_domain": "cobrother.com"}


def test_build_web_hosting_params_derives_username_from_domain():
    params = build_order_parameters("web_hosting", "starter", "monthly", {"primaryDomain": "My-Business.co.in"})
    assert params["primary_domain"] == "my-business.co.in"
    assert params["cpanel_username"] == "mybusiness"


def test_build_web_hosting_params_missing_domain_sends_no_username():
    params = build_order_parameters("web_hosting", "starter", "monthly", {})
    assert params == {}


def test_build_business_phone_params_with_phone_number():
    params = build_order_parameters("business_phone", "starter", "monthly", {"phoneNumber": "+919876543210"})
    assert params == {"phone_number": "+919876543210"}


def test_build_business_phone_params_with_area_code():
    params = build_order_parameters("business_phone", "starter", "monthly", {"areaCode": "91"})
    assert params == {"area_code": "91"}


def test_build_business_phone_params_prefers_phone_number():
    params = build_order_parameters("business_phone", "starter", "monthly", {
        "phoneNumber": "+919876543210",
        "areaCode": "91",
    })
    assert params == {"phone_number": "+919876543210"}


def test_build_business_phone_params_without_input_returns_empty():
    # area_code="auto" is NOT valid for live purchases — no input must yield
    # an empty param set so the caller can move the purchase to needs-input
    # instead of calling POST /orders.
    params = build_order_parameters("business_phone", "starter", "monthly", {})
    assert params == {}


def test_build_invoice_ai_params():
    params = build_order_parameters("invoice_ai", "starter", "monthly", {"businessName": "My Business"})
    assert params == {"business_name": "My Business"}


def test_build_appointments_params():
    params = build_order_parameters("appointments", "starter", "monthly", {"businessName": "My Business"})
    assert params == {"business_name": "My Business"}


def test_build_docsign_params():
    params = build_order_parameters("docsign", "starter", "monthly", {"companyName": "My Company"})
    assert params == {"company_name": "My Company"}


def test_build_params_strips_none_values():
    params = build_order_parameters("vpn", "pro", "monthly", {})
    assert "server_id" not in params
    assert "port_id" not in params


def test_build_unknown_product_key_returns_empty():
    params = build_order_parameters("unknown_product", "starter", "monthly")
    assert params == {}


def test_get_mapped_services_returns_all_confirmed():
    services = get_mapped_services()
    assert isinstance(services, list)
    assert len(services) == 16
    assert "ai-business-suite" in services
    assert "website-builder" in services
    assert "wordpress-plugin-pack" not in services


def test_derive_cpanel_username_examples():
    assert derive_cpanel_username("example.com") == "example"
    assert derive_cpanel_username("my-business.co.in") == "mybusiness"
    assert derive_cpanel_username("sub.example.com.au") == "example"
    assert derive_cpanel_username("HTTPS://EXAMPLE.COM/") == "example"
    assert derive_cpanel_username("notadomain") == ""


def test_validate_order_input_business_phone():
    # Business Phone requires areaCode OR phoneNumber (never "auto").
    ok, missing = validate_order_input("business-phone", {})
    assert ok is False
    assert missing == ["areaCode"]
    ok, missing = validate_order_input("business-phone", {"areaCode": "415"})
    assert ok is True
    assert missing == []
    ok, missing = validate_order_input("business-phone", {"phoneNumber": "+14155551234"})
    assert ok is True
    assert missing == []


def test_validate_order_input_web_hosting():
    ok, missing = validate_order_input("web-hosting", {})
    assert ok is False
    assert missing == ["primaryDomain"]
    ok, missing = validate_order_input("web-hosting", {"primaryDomain": "example.com"})
    assert ok is True


def test_validate_order_input_other_services_pass():
    ok, missing = validate_order_input("vpn", {})
    assert ok is True
    assert missing == []
