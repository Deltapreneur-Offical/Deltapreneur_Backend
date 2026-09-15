"""Tests for ResellPortal product mapper."""
from app.service.resellportal.product_mapper import (
    PRODUCT_KEY_MAP,
    CONFIRMED_PRODUCT_KEYS,
    PARAM_BUILDERS,
    build_order_parameters,
    derive_cpanel_username,
    get_mapped_services,
    get_product_key,
    is_confirmed_product_key,
    is_provider_mapped,
    resolve_product_key,
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
        "wordpress-plugin-pack",
    ]
    for slug in confirmed:
        assert get_product_key(slug) is not None, f"Missing product_key for {slug}"
        assert is_provider_mapped(slug) is True
    assert set(PRODUCT_KEY_MAP.values()) == CONFIRMED_PRODUCT_KEYS


def test_product_key_map_includes_wordpress_plugin_installer():
    assert get_product_key("wordpress-plugin-pack") == "wp_plugin_installer"
    assert is_provider_mapped("wordpress-plugin-pack") is True


def test_build_ai_business_tools_params():
    assert build_order_parameters("ai_business_tools", "pro", "monthly") == {}
    params = build_order_parameters(
        "ai_business_tools",
        "pro",
        "monthly",
        {"aiTools": ["content-marketing-suite"]},
    )
    assert params == {"ai_tools": ["content-marketing-suite"]}


def test_build_cloud_storage_params_with_metadata():
    params = build_order_parameters("cloud_storage", "starter", "monthly", {"storagePlan": "200gb"})
    assert params == {"storage_plan": "200gb"}


def test_build_cloud_storage_params_does_not_invent_plan():
    params = build_order_parameters("cloud_storage", "starter", "monthly")
    assert params == {}


def test_build_cloud_storage_params_invalid_returns_empty():
    params = build_order_parameters("cloud_storage", "starter", "monthly", {"storagePlan": "invalid"})
    assert params == {}


def test_build_esim_params():
    params = build_order_parameters("esim", "starter", "monthly", {"packageCode": "global-5gb"})
    assert params == {"package_code": "global-5gb"}


def test_build_esim_params_does_not_invent_package_code():
    params = build_order_parameters("esim", "starter", "monthly", {})
    assert params == {}


def test_build_smm_params():
    params = build_order_parameters(
        "smm",
        "starter",
        "monthly",
        {"serviceId": "insta-likes", "link": "https://example.com", "quantity": 500},
    )
    assert params == {"service_id": "insta-likes", "link": "https://example.com", "quantity": 500}


def test_build_smm_params_does_not_invent_fulfillment_values():
    params = build_order_parameters("smm", "starter", "monthly", {})
    assert params == {}


def test_build_vpn_params():
    params = build_order_parameters("vpn", "pro", "monthly", {"vpnUsername": "buyer-vpn"})
    assert params == {"vpn_username": "buyer-vpn"}


def test_build_vpn_params_does_not_send_server_or_port():
    params = build_order_parameters("vpn", "pro", "monthly", {"serverId": "us-east-1", "portId": "443"})
    assert params == {}


def test_build_web_hosting_params():
    params = build_order_parameters("web_hosting", "starter", "monthly", {
        "cpanelUsername": "cobrother",
        "primaryDomain": "cobrother.com",
    })
    assert params == {"cpanel_username": "cobrother", "primary_domain": "cobrother.com", "plan": "starter"}


def test_build_web_hosting_params_derives_username_from_domain():
    params = build_order_parameters("web_hosting", "starter", "monthly", {"primaryDomain": "My-Business.co.in"})
    assert params["primary_domain"] == "my-business.co.in"
    assert params["cpanel_username"] == "mybusiness"
    assert params["plan"] == "starter"


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
    params = build_order_parameters(
        "invoice_ai",
        "starter",
        "monthly",
        {"subdomain": "mybiz", "businessName": "My Business", "logoUrl": "https://cdn.test/logo.png", "primaryColor": "#123456"},
    )
    assert params == {
        "subdomain": "mybiz",
        "business_name": "My Business",
        "logo_url": "https://cdn.test/logo.png",
        "primary_color": "#123456",
    }


def test_build_appointments_params():
    params = build_order_parameters(
        "appointments",
        "starter",
        "monthly",
        {"subdomain": "bookme", "businessName": "My Business", "secondaryColor": "#654321"},
    )
    assert params == {
        "subdomain": "bookme",
        "business_name": "My Business",
        "secondary_color": "#654321",
    }


def test_build_docsign_params():
    params = build_order_parameters("docsign", "starter", "monthly", {"companyName": "My Company"})
    assert params == {"company_name": "My Company"}


def test_build_docsign_params_does_not_invent_company_name():
    assert build_order_parameters("docsign", "starter", "monthly", {}) == {}


def test_build_params_strips_none_values():
    params = build_order_parameters("vpn", "pro", "monthly", {})
    assert params == {}


def test_build_unknown_product_key_returns_empty():
    params = build_order_parameters("unknown_product", "starter", "monthly")
    assert params == {}


def test_get_mapped_services_returns_all_confirmed():
    services = get_mapped_services()
    assert isinstance(services, list)
    assert len(services) == 17
    assert "ai-business-suite" in services
    assert "website-builder" in services
    assert "wordpress-plugin-pack" in services


def test_confirmed_product_key_resolution_prefers_contract_mapping():
    assert is_confirmed_product_key("email_marketing") is True
    assert is_confirmed_product_key("unknown") is False
    assert resolve_product_key("email-marketing", "wrong_key") == "email_marketing"
    assert resolve_product_key("unknown-slug", "email_marketing") == "email_marketing"
    assert resolve_product_key("unknown-slug", "wrong_key") is None


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


def test_validate_order_input_new_required_contract_fields():
    assert validate_order_input("ai-business-suite", {}) == (False, ["aiTools"])
    assert validate_order_input("ai-business-suite", {"aiTools": ["content-marketing-suite"]}) == (True, [])
    assert validate_order_input("cloud-storage", {}) == (False, ["storagePlan"])
    assert validate_order_input("cloud-storage", {"storagePlan": "200gb"}) == (True, [])
    assert validate_order_input("cloud-storage", {"storagePlan": "invalid"}) == (False, ["storagePlan"])
    assert validate_order_input("document-signer", {}) == (False, ["companyName"])
    assert validate_order_input("document-signer", {"companyName": "Acme"}) == (True, [])
    assert validate_order_input("email-marketing", {"selectedPlan": "starter"}) == (True, [])
    assert validate_order_input("email-marketing", {"selectedPlan": "pro"}) == (True, [])
    assert validate_order_input("email-marketing", {"selectedPlan": "enterprise"}) == (False, ["sendingPlan"])
    assert validate_order_input("email-marketing", {"sendingPlan": "business"}) == (True, [])
    assert validate_order_input("invoice-ai", {}) == (False, ["subdomain"])
    assert validate_order_input("invoice-ai", {"subdomain": "billing"}) == (True, [])
    assert validate_order_input("appointment-booking", {}) == (False, ["subdomain"])
    assert validate_order_input("smm-growth", {}) == (False, ["link", "quantity", "serviceId"])
    assert validate_order_input(
        "smm-growth",
        {"serviceId": "svc", "link": "https://social.example/post", "quantity": 100},
    ) == (True, [])
    assert validate_order_input("esim", {}) == (False, ["packageCode"])
    assert validate_order_input("esim", {"packageCode": "global-5gb"}) == (True, [])
    assert validate_order_input("wordpress-plugin-pack", {}) == (
        False,
        ["author", "description", "logoUrl", "pluginName"],
    )


def test_validate_order_input_other_services_pass():
    ok, missing = validate_order_input("vpn", {})
    assert ok is True
    assert missing == []
