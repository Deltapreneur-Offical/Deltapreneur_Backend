"""Admin Reseller Portal purchase identification and access-details security."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.controller.technology.technology_services_controller import router as technology_router
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.exceptions import register_exception_handlers
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.core.config import settings
from app.service.technology.provider_access import (
    access_email_delivery_status,
    access_email_payload,
    admin_access_detail_fields,
    customer_access_email_fields,
    dump_provider_credentials,
    filter_admin_subscriptions_by_email,
    load_provider_credentials,
    serialize_admin_access_details,
    serialize_admin_subscription_list_item,
    serialize_customer_subscription,
    store_subscription_credentials,
)
from app.service.auth.email_templates import technology_service_access_email_template


OWNER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
SUB_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
CRM_PASSWORD = "crm-test-password"
LIB_TOKEN = "REDACTED_PROVIDER_ACCESS_TOKEN"
CRM_LOGIN_URL_A = "https://app.acme-crm.io/s/cust-a"
CRM_LOGIN_URL_B = "https://app.acme-crm.io/s/cust-b"


class _FakeQuery:
    def __init__(self, rows):
        self.rows = list(rows)

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None


class _FakeDB:
    def __init__(self, *, subs=None, users=None):
        self.subs = list(subs or [])
        self.users = list(users or [])
        self.added = []
        self.commits = 0

    def query(self, model):
        name = getattr(model, "__name__", str(model))
        if "User" in name:
            return _FakeQuery(self.users)
        return _FakeQuery(self.subs)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def flush(self):
        return None

    def rollback(self):
        return None


def _user(*, user_id=OWNER_ID, email="buyer@test.local", role=UserRole.USER, firstname="Kushi", lastname="Ladagi"):
    return AppUser(
        id=uuid.UUID(user_id),
        email=email,
        firstname=firstname,
        lastname=lastname,
        role=role,
        active=True,
        email_verified=True,
        profile_complete=True,
    )


def _sub(**overrides):
    base = dict(
        id=uuid.UUID(SUB_ID),
        user_id=OWNER_ID,
        service_slug="crm",
        service_name="CRM",
        plan_code="starter",
        billing_cycle="monthly",
        price=2809.58,
        currency="INR",
        status="ACTIVE",
        payment_status="CAPTURED",
        provider_subscription_id="test_svc_514e5091e281",
        provider_order_id=None,
        credentials_json=dump_provider_credentials(
            {"email": "test+client@example.com", "password": CRM_PASSWORD}
        ),
        last_provider_status="ACTIVE",
        last_provider_error=None,
        needs_review=False,
        provision_attempts=1,
        next_retry_at=None,
        current_period_start=None,
        current_period_end=None,
        auto_renew=True,
        access_email_sent=False,
        access_email_status="PENDING",
        razorpay_order_id="order_test",
        razorpay_payment_id="pay_test",
        created_at=datetime.now(timezone.utc),
        is_deleted=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _client(*, user=None, subs=None, users=None):
    app = FastAPI()
    app.include_router(technology_router)
    register_exception_handlers(app)
    db = _FakeDB(subs=subs or [], users=users or [])

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    client.fake_db = db
    return client


def test_admin_list_identifies_purchase_by_customer_email():
    crm = _sub()
    other = _sub(
        id=uuid.uuid4(),
        user_id=OTHER_ID,
        service_slug="link-in-bio",
        service_name="Link in Bio",
        credentials_json=None,
        provider_subscription_id="lib-1",
    )
    buyer = _user()
    other_user = _user(user_id=OTHER_ID, email="second@test.local", firstname="Other", lastname="Buyer")
    client = _client(
        user=_user(role=UserRole.ADMIN, email="admin@test.local", firstname="Admin"),
        subs=[crm, other],
        users=[buyer, other_user],
    )
    res = client.get(
        "/api/v1/technology-services/admin/subscriptions",
        params={"email": "buyer@test.local"},
    )
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["customer_email"] == "buyer@test.local"
    assert rows[0]["customer_name"] == "Kushi Ladagi"
    assert rows[0]["service_name"] == "CRM"
    assert rows[0]["service_slug"] == "crm"


def test_admin_list_includes_provider_identifiers_without_credentials():
    sub = _sub(provider_order_id="ORD-99")
    row = serialize_admin_subscription_list_item(sub, user=_user())
    assert row["provider_subscription_id"] == "test_svc_514e5091e281"
    assert row["provider_order_id"] == "ORD-99"
    assert row["payment_status"] == "CAPTURED"
    assert row["status"] == "ACTIVE"
    assert row["has_access_information"] is True
    dumped = json.dumps(row)
    assert CRM_PASSWORD not in dumped
    assert "test+client@example.com" not in dumped
    assert "credentials" not in row
    assert "fields" not in row


def test_admin_can_distinguish_two_customers_same_service():
    first = serialize_admin_subscription_list_item(
        _sub(),
        user=_user(email="one@test.local", firstname="One"),
    )
    second = serialize_admin_subscription_list_item(
        _sub(id=uuid.uuid4(), user_id=OTHER_ID),
        user=_user(user_id=OTHER_ID, email="two@test.local", firstname="Two", lastname="Buyer"),
    )
    rows = filter_admin_subscriptions_by_email([first, second], "two@test.local")
    assert len(rows) == 1
    assert rows[0]["customer_email"] == "two@test.local"
    assert first["customer_email"] != second["customer_email"]


def test_admin_access_details_is_protected():
    sub = _sub()
    users = [_user()]
    unauth = _client(user=None, subs=[sub], users=users)
    assert unauth.get(f"/api/v1/technology-services/admin/subscriptions/{SUB_ID}/access-details").status_code in (401, 403)

    customer = _client(user=_user(role=UserRole.USER), subs=[sub], users=users)
    res = customer.get(f"/api/v1/technology-services/admin/subscriptions/{SUB_ID}/access-details")
    assert res.status_code == 403
    assert CRM_PASSWORD not in res.text

    admin = _client(
        user=_user(role=UserRole.ADMIN, email="admin@test.local"),
        subs=[sub],
        users=users,
    )
    ok = admin.get(f"/api/v1/technology-services/admin/subscriptions/{SUB_ID}/access-details")
    assert ok.status_code == 200
    body = ok.json()
    assert body["access_available"] is True
    keys = {field["key"]: field for field in body["fields"]}
    assert keys["email"]["value"] == "test+client@example.com"
    assert keys["password"]["value"] == CRM_PASSWORD
    assert keys["password"]["sensitive"] is True


def test_customer_apis_do_not_include_decrypted_credentials():
    serialized = serialize_customer_subscription(_sub())
    dumped = json.dumps(serialized)
    assert CRM_PASSWORD not in dumped
    assert serialized["credentials"] == {}
    assert serialized.get("managePath") is None
    assert "Manage Link in Bio" not in dumped


def test_missing_credentials_are_handled_safely():
    empty = admin_access_detail_fields({})
    assert empty == []
    details = serialize_admin_access_details(
        _sub(credentials_json=None),
        user=_user(),
        admin_id="admin-1",
    )
    assert details["access_available"] is False
    assert details["message"] == "Access information not available"
    assert details["fields"] == []


def test_different_credential_structures_are_not_assumed():
    crm = admin_access_detail_fields({"email": "a@b.c", "password": "secret"})
    assert {f["key"] for f in crm} == {"email", "password"}
    assert "username" not in {f["key"] for f in crm}

    token = admin_access_detail_fields({"access_token": LIB_TOKEN, "username": "kushi"})
    assert {f["key"] for f in token} == {"access_token", "username"}
    assert next(f for f in token if f["key"] == "access_token")["sensitive"] is True

    license_only = admin_access_detail_fields({"license_key": "LIC-1"})
    assert license_only == [
        {"key": "license_key", "label": "License Key", "value": "LIC-1", "sensitive": True}
    ]


def test_admin_access_details_do_not_invent_fields():
    fields = admin_access_detail_fields({"email": "only@example.com"})
    assert [f["key"] for f in fields] == ["email"]
    assert all(f["key"] != "password" for f in fields)
    assert all(f["key"] != "access_url" for f in fields)


def test_access_email_payload_decrypts_active_captured_credentials_only():
    payload = access_email_payload(_sub(), customer_name="Kushi Ladagi")
    assert payload is not None
    assert payload["customer_name"] == "Kushi Ladagi"
    fields = {field["key"]: field for field in payload["access_fields"]}
    assert fields["email"]["label"] == "Login email"
    assert fields["email"]["value"] == "test+client@example.com"
    assert fields["password"]["value"] == CRM_PASSWORD

    assert access_email_payload(_sub(status="PENDING")) is None
    assert access_email_payload(_sub(status="PROVISIONING_FAILED")) is None
    assert access_email_payload(_sub(payment_status="FAILED")) is None
    assert access_email_payload(_sub(access_email_sent=True)) is None
    assert access_email_payload(_sub(access_email_sent=True), allow_already_sent=True) is not None


def test_access_email_fields_strip_resellportal_urls_without_fabricating():
    fields, access_url = customer_access_email_fields(
        {
            "access_url": "https://panel.resellportal.com/app?access_token=secret",
            "username": "buyer",
            "password": "safe-test-password",
        }
    )
    assert access_url is None
    dumped = json.dumps(fields)
    assert "resellportal" not in dumped.lower()
    assert "access_token" not in dumped.lower()
    assert {field["key"] for field in fields} == {"username", "password"}


def test_access_email_fields_include_safe_url_button_and_varied_credentials():
    fields, access_url = customer_access_email_fields(
        {
            "access_url": "https://activate.acme-apps.io/start",
            "license_key": "LIC-TEST-1",
            "activation_code": "ACT-123",
            "qr": {"issuer": "test", "code": "QR-ONLY"},
        }
    )
    assert access_url == "https://activate.acme-apps.io/start"
    keys = {field["key"] for field in fields}
    assert keys == {"access_url", "license_key", "activation_code", "qr"}
    assert "password" not in keys

    html = technology_service_access_email_template(
        customer_name="Kushi",
        service_name="CRM",
        plan_name="Starter",
        billing_cycle="monthly",
        service_status="Active",
        access_fields=fields,
        access_url=access_url,
        activated_at="11 Sep 2026",
        purchase_date="11 Sep 2026",
    )
    assert "LIC-TEST-1" in html
    assert "ACT-123" in html
    assert "https://activate.acme-apps.io/start" in html
    assert "Open login page" in html
    assert "resellportal" not in html.lower()


def test_access_email_fields_do_not_send_provider_tokens():
    fields, access_url = customer_access_email_fields(
        {
            "access_token": LIB_TOKEN,
            "api_key": "provider-api-key",
            "username": "buyer",
            "activation_code": "ACT-OK",
        }
    )
    dumped = json.dumps(fields)
    assert access_url is None
    assert LIB_TOKEN not in dumped
    assert "provider-api-key" not in dumped
    assert {field["key"] for field in fields} == {"username", "activation_code"}


def test_admin_list_endpoint_omits_credentials_until_explicit_retrieval():
    sub = _sub()
    admin = _client(
        user=_user(role=UserRole.ADMIN, email="admin@test.local"),
        subs=[sub],
        users=[_user()],
    )
    listed = admin.get("/api/v1/technology-services/admin/subscriptions")
    assert listed.status_code == 200
    assert CRM_PASSWORD not in listed.text
    assert "test+client@example.com" not in listed.text
    row = listed.json()[0]
    assert row["has_access_information"] is True
    details = admin.get(f"/api/v1/technology-services/admin/subscriptions/{SUB_ID}/access-details")
    assert details.status_code == 200
    assert CRM_PASSWORD in details.text


def test_admin_list_access_email_status_mapping():
    sent = serialize_admin_subscription_list_item(
        _sub(access_email_sent=True, access_email_status="SENT"),
        user=_user(),
    )
    pending = serialize_admin_subscription_list_item(
        _sub(access_email_sent=False, access_email_status="PENDING"),
        user=_user(),
    )
    failed = serialize_admin_subscription_list_item(
        _sub(access_email_sent=False, access_email_status="FAILED"),
        user=_user(),
    )
    assert sent["access_email_status"] == "SENT"
    assert sent["access_email_sent"] is True
    assert pending["access_email_status"] == "PENDING"
    assert failed["access_email_status"] == "FAILED"
    assert "access_email_sent_at" not in sent
    assert CRM_PASSWORD not in json.dumps(sent)
    assert access_email_delivery_status(_sub(access_email_sent=True, access_email_status="FAILED")) == "SENT"
    provisioning_noise = _sub(
        access_email_sent=False,
        access_email_status="PENDING",
        last_provider_error="provider timeout",
        email_sent=True,
        confirmation_sent=True,
    )
    assert access_email_delivery_status(provisioning_noise) == "PENDING"


def test_admin_list_endpoint_includes_access_email_status():
    sub = _sub(access_email_sent=True, access_email_status="SENT")
    admin = _client(
        user=_user(role=UserRole.ADMIN, email="admin@test.local"),
        subs=[sub],
        users=[_user()],
    )
    listed = admin.get("/api/v1/technology-services/admin/subscriptions")
    assert listed.status_code == 200
    row = listed.json()[0]
    assert row["access_email_status"] == "SENT"
    assert CRM_PASSWORD not in listed.text


RESEND_PATH = f"/api/v1/technology-services/admin/subscriptions/{SUB_ID}/resend-access-email"


def test_resend_access_email_is_admin_only():
    sub = _sub(access_email_sent=True, access_email_status="SENT")
    users = [_user()]
    unauth = _client(user=None, subs=[sub], users=users)
    assert unauth.post(RESEND_PATH).status_code in (401, 403)

    customer = _client(user=_user(role=UserRole.USER), subs=[sub], users=users)
    res = customer.post(RESEND_PATH)
    assert res.status_code == 403
    assert CRM_PASSWORD not in res.text
    assert "access_fields" not in res.text


def test_resend_access_email_sends_existing_template_without_reprovisioning():
    period_start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    period_end = datetime(2026, 10, 1, tzinfo=timezone.utc)
    creds = dump_provider_credentials({"email": "test+client@example.com", "password": CRM_PASSWORD})
    sub = _sub(
        access_email_sent=True,
        access_email_status="SENT",
        current_period_start=period_start,
        current_period_end=period_end,
        credentials_json=creds,
    )
    admin = _client(
        user=_user(role=UserRole.ADMIN, email="admin@test.local"),
        subs=[sub],
        users=[_user()],
    )
    with (
        patch(
            "app.service.auth.mail_service.MailService.send_technology_service_access_email",
            new_callable=AsyncMock,
        ) as send_mail,
        patch("app.integrations.resellportal.client.get_resellportal_client") as get_provider,
        patch("app.integrations.razorpay.client.create_order") as create_order,
        patch("app.integrations.razorpay.client.refund_payment") as refund_payment,
    ):
        res = admin.post(RESEND_PATH)

    assert res.status_code == 200
    body = res.json()
    assert body == {
        "success": True,
        "message": "Access email sent.",
        "access_email_status": "SENT",
        "access_email_sent": True,
    }
    assert CRM_PASSWORD not in res.text
    assert "test+client@example.com" not in res.text
    send_mail.assert_awaited_once()
    kwargs = send_mail.await_args.kwargs
    assert kwargs["to_email"] == "buyer@test.local"
    fields = {field["key"]: field for field in kwargs["access_fields"]}
    assert fields["password"]["value"] == CRM_PASSWORD
    get_provider.assert_not_called()
    create_order.assert_not_called()
    refund_payment.assert_not_called()
    assert admin.fake_db.added == []
    assert len(admin.fake_db.subs) == 1
    assert sub.access_email_sent is True
    assert sub.access_email_status == "SENT"
    assert sub.status == "ACTIVE"
    assert sub.payment_status == "CAPTURED"
    assert sub.current_period_start == period_start
    assert sub.current_period_end == period_end
    assert sub.credentials_json == creds
    assert str(sub.credentials_json).startswith("enc:v1:")
    assert sub.razorpay_order_id == "order_test"
    assert sub.razorpay_payment_id == "pay_test"


def test_resend_access_email_rejects_ineligible_subscription():
    pending = _sub(status="PENDING", access_email_sent=False)
    admin = _client(
        user=_user(role=UserRole.ADMIN, email="admin@test.local"),
        subs=[pending],
        users=[_user()],
    )
    with patch(
        "app.service.auth.mail_service.MailService.send_technology_service_access_email",
        new_callable=AsyncMock,
    ) as send_mail:
        res = admin.post(RESEND_PATH)
    assert res.status_code == 400
    assert "active" in res.json()["detail"].lower()
    send_mail.assert_not_called()
    assert pending.access_email_sent is False


def test_resend_access_email_smtp_failure_marks_failed_without_resetting_success():
    failed_sub = _sub(access_email_sent=False, access_email_status="PENDING")
    admin = _client(
        user=_user(role=UserRole.ADMIN, email="admin@test.local"),
        subs=[failed_sub],
        users=[_user()],
    )
    with patch(
        "app.service.auth.mail_service.MailService.send_technology_service_access_email",
        new_callable=AsyncMock,
        side_effect=RuntimeError("SMTP rejected"),
    ):
        res = admin.post(RESEND_PATH)
    assert res.status_code == 502
    assert CRM_PASSWORD not in res.text
    assert failed_sub.access_email_sent is False
    assert failed_sub.access_email_status == "FAILED"
    assert access_email_delivery_status(failed_sub) == "FAILED"


def _crm_access_html(payload):
    return technology_service_access_email_template(
        customer_name=payload["customer_name"],
        service_name=payload["service_name"],
        plan_name=payload["plan_name"],
        billing_cycle=payload["billing_cycle"],
        service_status=payload["service_status"],
        access_fields=payload["access_fields"],
        access_url=payload["access_url"],
        activated_at=payload.get("activated_at"),
        purchase_date=payload.get("purchase_date"),
    )


def test_crm_access_email_contains_this_customer_login_url_email_and_password():
    sub = _sub(
        credentials_json=dump_provider_credentials(
            {
                "login_url": CRM_LOGIN_URL_A,
                "email": "buyer-a@crm.local",
                "password": CRM_PASSWORD,
                "access_token": LIB_TOKEN,
                "order_id": "internal-order-a",
                "service_id": "should-not-email",
            }
        )
    )
    payload = access_email_payload(sub, customer_name="Buyer A")
    assert payload is not None
    assert payload["service_name"] == "CRM"
    assert payload["access_url"] == CRM_LOGIN_URL_A
    fields = {field["key"]: field for field in payload["access_fields"]}
    assert fields["email"]["value"] == "buyer-a@crm.local"
    assert fields["password"]["value"] == CRM_PASSWORD
    assert fields["login_url"]["value"] == CRM_LOGIN_URL_A
    assert "access_token" not in fields
    assert "order_id" not in fields
    assert "service_id" not in fields

    html = _crm_access_html(payload)
    assert "CRM" in html
    assert CRM_LOGIN_URL_A in html
    assert "buyer-a@crm.local" in html
    assert CRM_PASSWORD in html
    assert "Open login page" in html
    assert "resellportal" not in html.lower()
    assert "panel.resellportal.com" not in html
    assert LIB_TOKEN not in html
    assert "internal-order-a" not in html
    assert "access_token" not in html.lower()
    assert "api_key" not in html.lower()
    assert "bearer" not in html.lower()


def test_crm_login_url_belongs_to_this_subscription_not_another_customer():
    first = access_email_payload(
        _sub(
            credentials_json=dump_provider_credentials(
                {
                    "login_url": CRM_LOGIN_URL_A,
                    "email": "buyer-a@crm.local",
                    "password": "pw-a",
                }
            )
        )
    )
    second = access_email_payload(
        _sub(
            id=uuid.uuid4(),
            user_id=OTHER_ID,
            credentials_json=dump_provider_credentials(
                {
                    "login_url": CRM_LOGIN_URL_B,
                    "email": "buyer-b@crm.local",
                    "password": "pw-b",
                }
            )
        )
    )
    assert first is not None and second is not None
    assert first["access_url"] == CRM_LOGIN_URL_A
    assert second["access_url"] == CRM_LOGIN_URL_B
    assert first["access_url"] != second["access_url"]
    first_fields = {field["key"]: field["value"] for field in first["access_fields"]}
    second_fields = {field["key"]: field["value"] for field in second["access_fields"]}
    assert first_fields["email"] == "buyer-a@crm.local"
    assert second_fields["email"] == "buyer-b@crm.local"
    assert first_fields["password"] == "pw-a"
    assert second_fields["password"] == "pw-b"
    assert CRM_LOGIN_URL_B not in _crm_access_html(first)
    assert CRM_LOGIN_URL_A not in _crm_access_html(second)


def test_crm_email_does_not_invent_login_url_when_provider_did_not_store_one():
    payload = access_email_payload(_sub())
    assert payload is not None
    assert payload["access_url"] is None
    html = _crm_access_html(payload)
    assert "crmportal.resellportal.com" not in html
    assert "panel.resellportal.com" not in html
    assert "workspace.cobrother.com" not in html
    assert "A login page URL was not included" in html
    fields = {field["key"]: field for field in payload["access_fields"]}
    assert fields["email"]["value"] == "test+client@example.com"
    assert fields["password"]["value"] == CRM_PASSWORD


def test_access_email_prefers_stored_login_url_over_access_url():
    fields, access_url = customer_access_email_fields(
        {
            "access_url": "https://legacy.acme-crm.io/old",
            "login_url": CRM_LOGIN_URL_A,
            "email": "buyer-a@crm.local",
            "password": CRM_PASSWORD,
        }
    )
    assert access_url == CRM_LOGIN_URL_A
    values = {field["value"] for field in fields}
    assert CRM_LOGIN_URL_A in values
    assert "https://legacy.acme-crm.io/old" in values


def test_credential_encryption_roundtrip_remains_unchanged():
    raw = {
        "email": "buyer-a@crm.local",
        "password": CRM_PASSWORD,
        "access_token": LIB_TOKEN,
        "login_url": CRM_LOGIN_URL_A,
    }
    dumped = dump_provider_credentials(raw)
    assert dumped.startswith("enc:v1:")
    assert CRM_PASSWORD not in dumped
    assert LIB_TOKEN not in dumped
    assert CRM_LOGIN_URL_A not in dumped
    loaded = load_provider_credentials(dumped)
    assert loaded == raw
    holder = SimpleNamespace(credentials_json=None)
    store_subscription_credentials(holder, raw)
    assert holder.credentials_json.startswith("enc:v1:")
    assert load_provider_credentials(holder.credentials_json) == raw
    serialized = serialize_customer_subscription(_sub(credentials_json=holder.credentials_json))
    assert serialized["credentials"] == {}
    assert CRM_PASSWORD not in json.dumps(serialized)
    assert LIB_TOKEN not in json.dumps(serialized)


def test_resend_sends_same_stored_login_information_without_reprovision_or_charge():
    creds = dump_provider_credentials(
        {
            "login_url": CRM_LOGIN_URL_A,
            "email": "buyer-a@crm.local",
            "password": CRM_PASSWORD,
        }
    )
    sub = _sub(
        access_email_sent=True,
        access_email_status="SENT",
        credentials_json=creds,
    )
    admin = _client(
        user=_user(role=UserRole.ADMIN, email="admin@test.local"),
        subs=[sub],
        users=[_user()],
    )
    with (
        patch(
            "app.service.auth.mail_service.MailService.send_technology_service_access_email",
            new_callable=AsyncMock,
        ) as send_mail,
        patch("app.integrations.resellportal.client.get_resellportal_client") as get_provider,
        patch("app.integrations.razorpay.client.create_order") as create_order,
        patch("app.integrations.razorpay.client.refund_payment") as refund_payment,
        patch("app.integrations.razorpay.client.fetch_payment") as fetch_payment,
        patch("app.integrations.razorpay.client.assert_captured_payment_for_order") as assert_captured,
    ):
        res = admin.post(RESEND_PATH)

    assert res.status_code == 200
    send_mail.assert_awaited_once()
    kwargs = send_mail.await_args.kwargs
    assert kwargs["access_url"] == CRM_LOGIN_URL_A
    fields = {field["key"]: field for field in kwargs["access_fields"]}
    assert fields["email"]["value"] == "buyer-a@crm.local"
    assert fields["password"]["value"] == CRM_PASSWORD
    get_provider.assert_not_called()
    create_order.assert_not_called()
    refund_payment.assert_not_called()
    fetch_payment.assert_not_called()
    assert_captured.assert_not_called()
    assert admin.fake_db.added == []
    assert sub.credentials_json == creds
    assert sub.status == "ACTIVE"
    assert sub.payment_status == "CAPTURED"
    assert sub.razorpay_order_id == "order_test"
    assert sub.razorpay_payment_id == "pay_test"
    assert CRM_PASSWORD not in res.text
    assert CRM_LOGIN_URL_A not in res.text


def test_link_in_bio_access_email_does_not_leak_provider_token():
    payload = access_email_payload(
        _sub(
            service_slug="link-in-bio",
            service_name="Link in Bio",
            credentials_json=dump_provider_credentials(
                {
                    "access_token": LIB_TOKEN,
                    "username": "kushi",
                    "access_url": "https://panel.resellportal.com/app?access_token=secret",
                    "api_key": "provider-api-key",
                }
            ),
        )
    )
    assert payload is not None
    dumped = json.dumps(payload)
    assert LIB_TOKEN not in dumped
    assert "provider-api-key" not in dumped
    assert "resellportal" not in dumped.lower()
    assert "access_token" not in dumped.lower()
    assert payload["access_url"] is None
    assert {field["key"] for field in payload["access_fields"]} == {"username"}
    html = _crm_access_html(payload)
    assert "kushi" in html
    assert LIB_TOKEN not in html
    assert "panel.resellportal.com" not in html


def test_production_access_email_omits_test_only_urls_and_credentials(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    fields, access_url = customer_access_email_fields(
        {
            "access_url": "https://workspace.cobrother.com/app/crm/abc",
            "login_url": CRM_LOGIN_URL_A,
            "link": "https://example.com",
            "package_code": "test-starter",
            "email": "test+client@example.com",
            "password": "live-enough-password",
            "server_id": "default",
            "port_id": "placeholder",
        }
    )
    dumped = json.dumps(fields)
    assert access_url == CRM_LOGIN_URL_A
    assert "workspace.cobrother.com" not in dumped
    assert "example.com" not in dumped
    assert "test-starter" not in dumped
    assert "test+client@example.com" not in dumped
    keys = {field["key"] for field in fields}
    assert "password" in keys
    assert "package_code" not in keys
    assert "link" not in keys
    assert "server_id" not in keys
    assert "port_id" not in keys


def test_mock_placeholder_and_admin_urls_are_never_emailed():
    fields, access_url = customer_access_email_fields(
        {
            "access_url": "https://workspace.cobrother.com/app/crm/x",
            "cpanel_url": "https://cpanel.example.com",
            "login_url": "https://crmportal.resellportal.com",
            "manage_url": "https://panel.resellportal.com/wp-json/resellportal/v1",
            "password": "ok-password",
            "api_token": "should-not-email",
            "bearer_token": "should-not-email",
        }
    )
    assert access_url is None
    dumped = json.dumps(fields)
    assert "workspace.cobrother.com" not in dumped
    assert "example.com" not in dumped
    assert "resellportal" not in dumped.lower()
    assert "should-not-email" not in dumped
    assert {field["key"] for field in fields} == {"password"}

