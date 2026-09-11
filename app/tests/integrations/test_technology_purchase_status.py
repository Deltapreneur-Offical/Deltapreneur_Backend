"""Customer activation labels and Failed Provisioning queue membership."""

from __future__ import annotations

from app.service.technology.technology_purchase_status import (
    customer_activation_view,
    is_failed_provisioning_queue_item,
    serialize_failed_provisioning_item,
)
from app.tests.integrations.test_technology_services_production_safety import _FakeSubscription


def test_captured_failed_provisioning_is_pending_activation_not_payment_failed():
    sub = _FakeSubscription(
        status="PROVISIONING_FAILED",
        provision_attempts=1,
        provider_order_id=None,
        needs_review=False,
    )
    view = customer_activation_view(sub, max_retries=5)
    assert view["paymentStatus"] == "COMPLETED"
    assert view["activationStatus"] == "PENDING_ACTIVATION"
    assert view["activationStatusLabel"] == "Pending Activation"
    assert view["provisioningStatus"] == "PROVISIONING_FAILED"
    assert view["completionStatus"] == "PENDING"


def test_captured_active_provisioning_is_active():
    sub = _FakeSubscription(status="ACTIVE", provider_order_id="ORD-1", provider_subscription_id="SUB-1")
    view = customer_activation_view(sub, max_retries=5)
    assert view["paymentStatus"] == "COMPLETED"
    assert view["activationStatus"] == "ACTIVE"
    assert view["activationStatusLabel"] == "Active"
    assert view["provisioningStatus"] == "ACTIVE"


def test_payment_failed_preserves_failed_state():
    sub = _FakeSubscription(status="PENDING")
    sub.payment_status = "FAILED"
    view = customer_activation_view(sub, max_retries=5)
    assert view["paymentStatus"] == "FAILED"
    assert view["activationStatus"] == "PAYMENT_FAILED"
    assert view["activationStatusLabel"] == "Payment Failed"


def test_terminal_needs_review_is_activation_issue_still_paid():
    sub = _FakeSubscription(
        status="PROVISIONING_FAILED",
        provision_attempts=5,
        needs_review=True,
        provider_order_id=None,
    )
    view = customer_activation_view(sub, max_retries=5)
    assert view["paymentStatus"] == "COMPLETED"
    assert view["activationStatus"] == "ACTIVATION_ISSUE"
    assert view["activationStatusLabel"] == "Activation Issue"


def test_failed_queue_includes_null_provider_order_id():
    sub = _FakeSubscription(
        status="PROVISIONING_FAILED",
        provision_attempts=1,
        provider_order_id=None,
        provider_subscription_id=None,
    )
    assert is_failed_provisioning_queue_item(sub) is True
    payload = serialize_failed_provisioning_item(sub, user_email="buyer@example.com")
    assert payload["provider_order_id"] is None
    assert payload["payment_status"] == "CAPTURED"
    assert payload["status"] == "PROVISIONING_FAILED"
    assert payload["user_email"] == "buyer@example.com"
    assert payload["retry_eligible"] is True


def test_failed_queue_excludes_active_and_unpaid_and_deleted():
    active = _FakeSubscription(status="ACTIVE", provider_order_id="ORD-1")
    unpaid = _FakeSubscription(status="PROVISIONING_FAILED")
    unpaid.payment_status = "FAILED"
    deleted = _FakeSubscription(status="PROVISIONING_FAILED", provider_order_id=None)
    deleted.is_deleted = True
    assert is_failed_provisioning_queue_item(active) is False
    assert is_failed_provisioning_queue_item(unpaid) is False
    assert is_failed_provisioning_queue_item(deleted) is False


def test_activation_labels_do_not_depend_on_product_name():
    phone = _FakeSubscription(
        service_slug="business-phone",
        service_name="Business Phone",
        status="PENDING",
    )
    other = _FakeSubscription(
        service_slug="cloud-storage",
        service_name="Cloud Storage",
        status="PENDING",
    )
    assert customer_activation_view(phone)["activationStatusLabel"] == customer_activation_view(other)["activationStatusLabel"]
