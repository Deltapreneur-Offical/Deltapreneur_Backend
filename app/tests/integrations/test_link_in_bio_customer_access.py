"""Link in Bio white-label customer access — ownership, secrets, and provision mapping."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controller.auth.auth_controller import get_current_user
from app.controller.technology.technology_services_controller import router as technology_router
from app.core.database import get_db
from app.core.exceptions import register_exception_handlers
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.integrations.resellportal.client import normalize_provision_response
from app.service.auth.email_templates import technology_purchase_confirmation_email_template
from app.service.technology.provider_access import (
    access_email_payload,
    confirmation_email_kwargs,
    credential_log_fields,
    dump_provider_credentials,
    is_fabricated_provider_id,
    load_provider_credentials,
    public_credentials,
    public_purchase_access_fields,
    real_provider_service_id,
    serialize_customer_subscription,
    store_subscription_credentials,
)


OWNER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
SERVICE_ID = "ABC123"
SECRET_TOKEN = "REDACTED_PROVIDER_ACCESS_TOKEN"


def _sub(**overrides):
    base = dict(
        id=uuid.uuid4(),
        user_id=OWNER_ID,
        service_slug="link-in-bio",
        service_name="Link in Bio",
        plan_code="starter",
        billing_cycle="monthly",
        price=476.0,
        currency="INR",
        status="ACTIVE",
        payment_status="CAPTURED",
        provider_subscription_id=SERVICE_ID,
        provider_order_id=None,
        credentials_json=dump_provider_credentials(
            {"access_token": SECRET_TOKEN, "username": "kushi"}
        ),
        current_period_start=None,
        current_period_end=None,
        auto_renew=True,
        created_at=datetime.now(timezone.utc),
        is_deleted=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _user(user_id=OWNER_ID):
    return AppUser(
        id=uuid.UUID(user_id),
        email="owner@test.local",
        role=UserRole.USER,
        active=True,
        email_verified=True,
        profile_complete=True,
    )


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.rows)


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def query(self, model):
        return _FakeQuery(self.rows)


def _access_client(*, user=None, rows=None):
    app = FastAPI()
    app.include_router(technology_router)
    register_exception_handlers(app)
    db = _FakeDB(rows or [])

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_confirmed_provision_response_maps_real_service_id():
    mapped = normalize_provision_response(
        {
            "success": True,
            "status": "ACTIVE",
            "service_id": SERVICE_ID,
            "credentials": {"access_token": SECRET_TOKEN, "username": "kushi"},
        },
        user_id=OWNER_ID,
        billing_cycle="monthly",
    )
    assert mapped["success"] is True
    assert mapped["status"] == "ACTIVE"
    assert mapped["service_id"] == SERVICE_ID
    assert mapped["provider_subscription_id"] == SERVICE_ID
    assert mapped["provider_order_id"] is None
    assert mapped["credentials"]["username"] == "kushi"
    assert mapped["credentials"]["access_token"] == SECRET_TOKEN
    assert not is_fabricated_provider_id(mapped["provider_subscription_id"], OWNER_ID)


def test_missing_service_id_is_incomplete_and_not_fabricated():
    mapped = normalize_provision_response(
        {"success": True, "status": "ACTIVE", "credentials": {"access_token": SECRET_TOKEN}},
        user_id=OWNER_ID,
        billing_cycle="monthly",
    )
    assert mapped["success"] is False
    assert mapped["status"] == "PROVISIONING_PENDING"
    assert mapped["provider_subscription_id"] is None
    assert mapped["service_id"] is None
    assert mapped["credentials"] == {}
    uid8 = OWNER_ID[:8]
    assert mapped.get("provider_order_id") != f"RSP-ORD-{uid8}"
    assert real_provider_service_id(mapped, user_id=OWNER_ID) is None


def test_fabricated_user_fallback_ids_are_rejected():
    uid8 = OWNER_ID[:8]
    assert is_fabricated_provider_id(f"RSP-ORD-{uid8}", OWNER_ID)
    assert is_fabricated_provider_id(f"RSP-SUB-{uid8}", OWNER_ID)
    assert not is_fabricated_provider_id("test_svc_c0c649428884", OWNER_ID)
    mapped = normalize_provision_response(
        {
            "success": True,
            "status": "ACTIVE",
            "service_id": f"RSP-SUB-{uid8}",
        },
        user_id=OWNER_ID,
        billing_cycle="monthly",
    )
    assert mapped["success"] is False
    assert mapped["provider_subscription_id"] is None


def test_credentials_are_encrypted_at_rest_and_not_plaintext():
    stored = dump_provider_credentials({"access_token": SECRET_TOKEN, "username": "kushi"})
    assert stored.startswith("enc:v1:")
    assert SECRET_TOKEN not in stored
    assert "kushi" not in stored
    loaded = load_provider_credentials(stored)
    assert loaded["access_token"] == SECRET_TOKEN
    assert loaded["username"] == "kushi"
    # legacy plaintext rows still load
    legacy = json.dumps({"username": "legacy", "access_token": "old"})
    assert load_provider_credentials(legacy)["username"] == "legacy"


def test_access_token_is_never_logged(caplog):
    with caplog.at_level(logging.INFO):
        logged = credential_log_fields({"access_token": SECRET_TOKEN, "username": "kushi"})
        normalize_provision_response(
            {
                "success": True,
                "status": "ACTIVE",
                "service_id": SERVICE_ID,
                "credentials": {"access_token": SECRET_TOKEN, "username": "kushi"},
            },
            user_id=OWNER_ID,
            billing_cycle="monthly",
        )
    assert SECRET_TOKEN not in str(logged)
    assert logged["has_access_token"] is True
    assert SECRET_TOKEN not in caplog.text
    assert "credentials" not in caplog.text or SECRET_TOKEN not in caplog.text


def test_customer_link_in_bio_access_route_removed():
    sub = _sub()
    client = _access_client(user=_user(), rows=[sub])
    res = client.get(
        "/api/v1/technology-services/link-in-bio/access",
        params={"service_id": SERVICE_ID},
    )
    assert res.status_code == 404
    assert SECRET_TOKEN not in res.text
    assert "access_token" not in res.text.lower()


def test_unauthenticated_user_cannot_read_customer_access_route():
    client = _access_client(user=None, rows=[_sub()])
    res = client.get(
        "/api/v1/technology-services/link-in-bio/access",
        params={"service_id": SERVICE_ID},
    )
    assert res.status_code in (401, 403, 404)
    assert SECRET_TOKEN not in res.text


def test_my_purchases_fields_never_include_access_token():
    active = _sub()
    pending = _sub(status="PENDING", provider_subscription_id=None)
    failed = _sub(status="PROVISIONING_FAILED")
    unpaid = _sub(payment_status="FAILED")
    for row in (active, pending, failed, unpaid):
        fields = public_purchase_access_fields(row)
        dumped = json.dumps(fields)
        assert "access_token" not in dumped
        assert "resellportal" not in dumped.lower()
        assert fields.get("managePath") is None
        assert fields.get("manageLabel") is None
        serialized = serialize_customer_subscription(row)
        body = json.dumps(serialized)
        assert "access_token" not in body
        assert serialized.get("managePath") is None
        assert serialized["credentials"] == {}
        assert "resellportal" not in body.lower()


def test_active_link_in_bio_has_no_customer_manage_cta():
    active = public_purchase_access_fields(_sub())
    pending = public_purchase_access_fields(_sub(status="PENDING"))
    other = public_purchase_access_fields(_sub(service_slug="ai-business-suite"))
    assert active["managePath"] is None
    assert active["manageLabel"] is None
    assert pending["managePath"] is None
    assert other["managePath"] is None
    serialized = serialize_customer_subscription(_sub())
    assert "Manage Link in Bio" not in json.dumps(serialized)
    assert serialized.get("managePath") is None


def test_public_credentials_strip_provider_host_and_token_query():
    public = public_credentials(
        {
            "access_token": SECRET_TOKEN,
            "username": "kushi",
            "access_url": "https://panel.resellportal.com/app?access_token=secret",
        },
        service_slug="ai-business-suite",
        provider_service_id="svc",
        status="ACTIVE",
        payment_status="CAPTURED",
    )
    assert "access_token" not in public
    assert public.get("access_url") is None
    assert "resellportal" not in json.dumps(public).lower()


def test_activation_email_has_no_manage_link_in_bio_cta():
    assert confirmation_email_kwargs(_sub()) == {}
    from app.service.technology.provider_access import confirmation_manage_url

    assert confirmation_manage_url(service_slug="link-in-bio", provider_service_id=SERVICE_ID) is None
    html = technology_purchase_confirmation_email_template(
        customer_name="Kushi",
        service_name="Link in Bio",
        plan_name="Starter",
        billing_cycle="monthly",
        cobrother_order_id="order-1",
        razorpay_payment_id="pay_test",
        amount_inr=561.68,
        purchase_date="10 Sep 2026",
        service_status="Active",
        provider_info=f"Service ID: {SERVICE_ID}",
        purchases_url="https://deltapreneur.com/purchases",
        manage_url=f"https://deltapreneur.com/link-in-bio/manage?service_id={SERVICE_ID}",
    )
    assert "Manage Link in Bio" not in html
    assert "/link-in-bio/manage" not in html
    assert "resellportal" not in html.lower()
    assert "access_token" not in html.lower()
    assert SECRET_TOKEN not in html
    assert "panel.resellportal.com" not in html
    assert "https://deltapreneur.com/purchases" in html


def test_store_subscription_credentials_does_not_keep_plaintext_token():
    sub = SimpleNamespace(credentials_json=None)
    store_subscription_credentials(sub, {"access_token": SECRET_TOKEN, "username": "kushi"})
    assert SECRET_TOKEN not in (sub.credentials_json or "")
    loaded = load_provider_credentials(sub.credentials_json)
    assert loaded["access_token"] == SECRET_TOKEN


def test_link_in_bio_access_email_never_includes_provider_token_or_admin_url():
    payload = access_email_payload(_sub())
    assert payload is not None
    dumped = json.dumps(payload)
    assert SECRET_TOKEN not in dumped
    assert "access_token" not in dumped.lower()
    assert "resellportal" not in dumped.lower()
    assert payload["access_url"] is None
    assert {field["key"] for field in payload["access_fields"]} == {"username"}
    serialized = serialize_customer_subscription(_sub())
    assert serialized["credentials"] == {}
