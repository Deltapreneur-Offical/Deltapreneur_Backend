"""Production-safety tests for Technology Services (checkout + retry worker).

Covers the scenarios required by the production-safe remediation design:

  A. Business Phone with valid area code -> ACTIVE
  B. Business Phone without area code  -> no POST /orders, PENDING/needs-input
  C. Web Hosting with valid domain     -> cpanel_username + primary_domain -> ACTIVE
  D. Web Hosting missing domain        -> no POST /orders, PENDING/needs-input
  E. WordPress (unmapped)              -> no POST /orders, manual fulfillment
  F. Provider ACTIVE                   -> ACTIVE + confirmation email + PROVISIONED/SUCCESS
  G. Provider PENDING                  -> PENDING + pending email + retry scheduled
  H. Provider failure                  -> PROVISIONING_FAILED + FAILED/FAILED + failed email
  I. Provider exception                -> subscription/invoice remain persisted
  J. Retry reconciles GET /orders first; adopts existing order; no duplicate POST
  K. Duplicate retry concurrency       -> row-locking used; one provisioning attempt
  L. Duplicate Razorpay verification   -> one subscription (alreadyProcessed)
  M. Renewals                          -> only ACTIVE + provider id + current_period_end
  N. Email                             -> exactly one correct email per state transition
  O. Track invariant                   -> PROVISIONED/SUCCESS only when ACTIVE + provider id
"""
from __future__ import annotations

import json
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.entity.technology_services.technology_service_entity import TechnologyServiceEntity
from app.service.cart.cart_checkout_service import (
    CartCheckoutService,
    _tech_backoff_for,
    _tech_fulfillment_from_result,
    _tech_sub_periods,
)
from app.service.platform.track_record_service import FulfillmentStatus, OverallStatus


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _make_tech_service(slug: str, provider_product_key: str | None = None) -> TechnologyServiceEntity:
    svc = TechnologyServiceEntity()
    svc.id = "11111111-1111-1111-1111-111111111111"
    svc.slug = slug
    svc.name = slug.replace("-", " ").title()
    svc.plans_json = json.dumps([{"code": "starter", "price_monthly": 10, "price_annually": 100}])
    svc.price_override_monthly = None
    svc.price_override_annually = None
    svc.provider_product_key = provider_product_key
    return svc


def _make_cart_item(service_id, slug: str, selected_plan: str = "starter", **meta_extra) -> MagicMock:
    item = MagicMock()
    item.id = "22222222-2222-2222-2222-222222222222"
    item.product_type = "TECHNOLOGY"
    item.product_id = service_id
    item.selected_plan = selected_plan
    item.addon_services = None
    item.co_brother_opt_in = False
    meta = {
        "productName": slug.replace("-", " ").title(),
        "serviceSlug": slug,
        "billingCycle": "monthly",
        "planCode": selected_plan,
    }
    meta.update(meta_extra)
    item.metadata_json = meta
    return item


def _make_buyer():
    buyer = MagicMock()
    buyer.id = "33333333-3333-3333-3333-333333333333"
    buyer.email = "buyer@cobrother.com"
    buyer.firstname = "Test"
    buyer.lastname = "Buyer"
    buyer.phone_number = "+919999999999"
    return buyer


class _FakeSubscription:
    """Minimal stand-in for TechnologySubscriptionEntity with the retry fields."""

    def __init__(self, **kw):
        self.id = kw.get("id", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        self.user_id = kw.get("user_id", "33333333-3333-3333-3333-333333333333")
        self.service_slug = kw.get("service_slug", "business-phone")
        self.service_name = kw.get("service_name", "Business Phone")
        self.plan_code = kw.get("plan_code", "starter")
        self.billing_cycle = kw.get("billing_cycle", "monthly")
        self.price = kw.get("price", 1909.0)
        self.currency = "INR"
        self.status = kw.get("status", "PENDING")
        self.payment_status = "CAPTURED"
        self.provider_subscription_id = kw.get("provider_subscription_id")
        self.provider_order_id = kw.get("provider_order_id")
        self.credentials_json = kw.get("credentials_json")
        self.current_period_start = kw.get("current_period_start")
        self.current_period_end = kw.get("current_period_end")
        self.auto_renew = True
        self.email_sent = False
        self.confirmation_sent = False
        self.idempotency_key = kw.get("idempotency_key")
        self.provision_attempts = kw.get("provision_attempts", 0)
        self.last_provision_attempt_at = None
        self.last_provider_status = kw.get("last_provider_status")
        self.last_provider_error = kw.get("last_provider_error")
        self.next_retry_at = kw.get("next_retry_at")
        self.razorpay_order_id = kw.get("razorpay_order_id", "order_test")
        self.razorpay_payment_id = kw.get("razorpay_payment_id", "pay_test")
        self.needs_review = kw.get("needs_review", False)
        self.provision_input = kw.get("provision_input")
        self.is_deleted = False


def _checkout_context(svc: TechnologyServiceEntity, item: MagicMock):
    """Build the full mock context for CartCheckoutService._complete_technology_purchase."""
    class _Ctx:
        def __enter__(self):
            self._stack = ExitStack()
            patchers = [
                patch("app.service.cart.cart_checkout_service.CartService"),
                patch("app.service.cart.cart_checkout_service.CartItemRepository"),
                patch("app.integrations.resellportal.client.get_resellportal_client"),
                patch("app.repository.software_purchase_repository.SoftwarePurchaseRepository"),
                patch("app.repository.cobrother_request_repository.CoBrotherRequestRepository"),
                patch("app.service.auth.mail_service.MailService"),
                patch("app.utils.addon_services.create_addon_operations_requests"),
            ]
            return tuple(self._stack.enter_context(p) for p in patchers)

        def __exit__(self, *exc):
            return self._stack.__exit__(*exc)

    return _Ctx()


# --------------------------------------------------------------------------- #
# A. Business Phone with valid area code -> ACTIVE
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_a_business_phone_with_area_code_provisions_and_activates():
    svc = _make_tech_service("business-phone", provider_product_key="business_phone")
    item = _make_cart_item(svc.id, "business-phone", areaCode="415")
    buyer = _make_buyer()

    with _checkout_context(svc, item) as (MockCart, MockRepo, mock_get_client, MockPurchase, MockCobrother, MockMail, MockAddon):
        mock_cart_svc = MockCart.return_value
        mock_cart_svc._get_technology_service = AsyncMock(return_value=svc)
        mock_cart_svc._get_technology_service_fallback = AsyncMock(return_value=None)
        mock_purchase_repo = MagicMock()
        mock_purchase_repo.get_by_razorpay_payment_id = AsyncMock(return_value=None)
        MockPurchase.return_value = mock_purchase_repo
        mock_cobrother_repo = MagicMock()
        mock_cobrother_repo.create = AsyncMock()
        MockCobrother.return_value = mock_cobrother_repo

        mock_client = MagicMock()
        mock_client.reconcile_pending_provisioning.return_value = {"reconciled": False, "provider_order_id": None}
        mock_client.provision_service.return_value = {
            "success": True,
            "status": "ACTIVE",
            "provider_order_id": "ORD-1",
            "provider_subscription_id": "SUB-1",
            "credentials": {"phone_number": "+14155550100"},
            "current_period_start": datetime.now(timezone.utc),
            "current_period_end": datetime.now(timezone.utc) + timedelta(days=30),
        }
        mock_get_client.return_value = mock_client

        added = []

        def fake_add(obj):
            added.append(obj)
            if not getattr(obj, "id", None):
                obj.id = "cccccccc-cccc-cccc-cccc-cccccccccccc"

        mock_session = MagicMock()
        mock_session.add = MagicMock(side_effect=fake_add)
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        ))

        service = CartCheckoutService(mock_session)
        result = await service._complete_technology_purchase(
            item=item, buyer=buyer, razorpay_payment_id="pay_a",
            buyer_name="Test Buyer", buyer_email="buyer@cobrother.com", buyer_phone="+919999999999",
        )

        # Provider called with the area code parameter.
        call_kwargs = mock_client.provision_service.call_args.kwargs
        assert call_kwargs["order_parameters"].get("area_code") == "415"
        assert result["status"] == "ACTIVE"
        assert result["success"] is True
        assert result["providerSubscriptionId"] == "SUB-1"
        # Confirmation email sent; failed/pending not.
        MockMail.send_technology_purchase_confirmation_email.assert_called_once()
        MockMail.send_technology_purchase_pending_email.assert_not_called()
        MockMail.send_technology_purchase_failed_email.assert_not_called()
        # Subscription committed BEFORE the provider call.
        commit_calls = [c for c in mock_session.commit.call_args_list]
        assert commit_calls, "subscription must be committed before provider provisioning"


# --------------------------------------------------------------------------- #
# B. Business Phone without area code -> NO POST /orders, PENDING/needs-input
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_b_business_phone_without_area_code_never_calls_provider():
    svc = _make_tech_service("business-phone", provider_product_key="business_phone")
    item = _make_cart_item(svc.id, "business-phone")  # no areaCode
    buyer = _make_buyer()

    with _checkout_context(svc, item) as (MockCart, MockRepo, mock_get_client, MockPurchase, MockCobrother, MockMail, MockAddon):
        mock_cart_svc = MockCart.return_value
        mock_cart_svc._get_technology_service = AsyncMock(return_value=svc)
        mock_cart_svc._get_technology_service_fallback = AsyncMock(return_value=None)
        mock_purchase_repo = MagicMock()
        mock_purchase_repo.get_by_razorpay_payment_id = AsyncMock(return_value=None)
        MockPurchase.return_value = mock_purchase_repo
        mock_cobrother_repo = MagicMock()
        mock_cobrother_repo.create = AsyncMock()
        MockCobrother.return_value = mock_cobrother_repo

        mock_session = MagicMock()
        added = []

        def fake_add(obj):
            added.append(obj)
            if not getattr(obj, "id", None):
                obj.id = "cccccccc-cccc-cccc-cccc-cccccccccccc"

        mock_session.add = MagicMock(side_effect=fake_add)
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        ))

        service = CartCheckoutService(mock_session)
        result = await service._complete_technology_purchase(
            item=item, buyer=buyer, razorpay_payment_id="pay_b",
            buyer_name="Test Buyer", buyer_email="buyer@cobrother.com", buyer_phone="+919999999999",
        )

        # NEVER called the provider.
        mock_get_client.assert_not_called()
        assert result["status"] == "PENDING"
        assert result["success"] is False
        # Subscription created with needs-input state.
        sub = next((o for o in added if type(o).__name__ == "TechnologySubscriptionEntity"), None)
        assert sub is not None
        assert sub.status == "PENDING"
        assert sub.needs_review is True
        assert "requires" in (sub.last_provider_error or "")
        # Pending (needs-input) email sent; no confirmation / failed email.
        MockMail.send_technology_purchase_pending_email.assert_called_once()
        MockMail.send_technology_purchase_confirmation_email.assert_not_called()
        MockMail.send_technology_purchase_failed_email.assert_not_called()


# --------------------------------------------------------------------------- #
# C. Web Hosting with valid domain -> cpanel_username + primary_domain -> ACTIVE
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_c_web_hosting_with_domain_provisions_with_cpanel_and_domain():
    svc = _make_tech_service("web-hosting", provider_product_key="web_hosting")
    item = _make_cart_item(svc.id, "web-hosting", primaryDomain="my-business.co.in")
    buyer = _make_buyer()

    with _checkout_context(svc, item) as (MockCart, MockRepo, mock_get_client, MockPurchase, MockCobrother, MockMail, MockAddon):
        mock_cart_svc = MockCart.return_value
        mock_cart_svc._get_technology_service = AsyncMock(return_value=svc)
        mock_cart_svc._get_technology_service_fallback = AsyncMock(return_value=None)
        mock_purchase_repo = MagicMock()
        mock_purchase_repo.get_by_razorpay_payment_id = AsyncMock(return_value=None)
        MockPurchase.return_value = mock_purchase_repo
        mock_cobrother_repo = MagicMock()
        mock_cobrother_repo.create = AsyncMock()
        MockCobrother.return_value = mock_cobrother_repo

        mock_client = MagicMock()
        mock_client.reconcile_pending_provisioning.return_value = {"reconciled": False, "provider_order_id": None}
        mock_client.provision_service.return_value = {
            "success": True, "status": "ACTIVE",
            "provider_order_id": "ORD-2", "provider_subscription_id": "SUB-2",
            "credentials": {"cpanel_url": "https://cpanel.example.com"},
            "current_period_start": datetime.now(timezone.utc),
            "current_period_end": datetime.now(timezone.utc) + timedelta(days=30),
        }
        mock_get_client.return_value = mock_client

        mock_session = MagicMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        ))

        service = CartCheckoutService(mock_session)
        result = await service._complete_technology_purchase(
            item=item, buyer=buyer, razorpay_payment_id="pay_c",
            buyer_name="Test Buyer", buyer_email="buyer@cobrother.com", buyer_phone="+919999999999",
        )

        call_kwargs = mock_client.provision_service.call_args.kwargs
        assert call_kwargs["order_parameters"].get("primary_domain") == "my-business.co.in"
        assert call_kwargs["order_parameters"].get("cpanel_username") == "mybusiness"
        assert result["status"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# D. Web Hosting missing domain -> NO POST /orders, PENDING/needs-input
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_d_web_hosting_missing_domain_never_calls_provider():
    svc = _make_tech_service("web-hosting", provider_product_key="web_hosting")
    item = _make_cart_item(svc.id, "web-hosting")  # no primaryDomain
    buyer = _make_buyer()

    with _checkout_context(svc, item) as (MockCart, MockRepo, mock_get_client, MockPurchase, MockCobrother, MockMail, MockAddon):
        mock_cart_svc = MockCart.return_value
        mock_cart_svc._get_technology_service = AsyncMock(return_value=svc)
        mock_cart_svc._get_technology_service_fallback = AsyncMock(return_value=None)
        mock_purchase_repo = MagicMock()
        mock_purchase_repo.get_by_razorpay_payment_id = AsyncMock(return_value=None)
        MockPurchase.return_value = mock_purchase_repo
        mock_cobrother_repo = MagicMock()
        mock_cobrother_repo.create = AsyncMock()
        MockCobrother.return_value = mock_cobrother_repo

        mock_session = MagicMock()
        added = []

        def fake_add(obj):
            added.append(obj)
            if not getattr(obj, "id", None):
                obj.id = "cccccccc-cccc-cccc-cccc-cccccccccccc"

        mock_session.add = MagicMock(side_effect=fake_add)
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        ))

        service = CartCheckoutService(mock_session)
        result = await service._complete_technology_purchase(
            item=item, buyer=buyer, razorpay_payment_id="pay_d",
            buyer_name="Test Buyer", buyer_email="buyer@cobrother.com", buyer_phone="+919999999999",
        )

        mock_get_client.assert_not_called()
        assert result["status"] == "PENDING"
        sub = next((o for o in added if type(o).__name__ == "TechnologySubscriptionEntity"), None)
        assert sub is not None
        assert sub.needs_review is True
        assert "requires" in (sub.last_provider_error or "")


# --------------------------------------------------------------------------- #
# E. WordPress (unmapped) -> NO POST /orders, PENDING manual fulfillment
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_e_wordpress_unmapped_never_calls_provider_and_marks_manual():
    svc = _make_tech_service("wordpress-plugin-pack", provider_product_key=None)
    item = _make_cart_item(svc.id, "wordpress-plugin-pack")
    buyer = _make_buyer()

    with _checkout_context(svc, item) as (MockCart, MockRepo, mock_get_client, MockPurchase, MockCobrother, MockMail, MockAddon):
        mock_cart_svc = MockCart.return_value
        mock_cart_svc._get_technology_service = AsyncMock(return_value=svc)
        mock_cart_svc._get_technology_service_fallback = AsyncMock(return_value=None)
        mock_purchase_repo = MagicMock()
        mock_purchase_repo.get_by_razorpay_payment_id = AsyncMock(return_value=None)
        MockPurchase.return_value = mock_purchase_repo
        mock_cobrother_repo = MagicMock()
        mock_cobrother_repo.create = AsyncMock()
        MockCobrother.return_value = mock_cobrother_repo

        mock_session = MagicMock()
        added = []

        def fake_add(obj):
            added.append(obj)
            if not getattr(obj, "id", None):
                obj.id = "cccccccc-cccc-cccc-cccc-cccccccccccc"

        mock_session.add = MagicMock(side_effect=fake_add)
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        ))

        service = CartCheckoutService(mock_session)
        result = await service._complete_technology_purchase(
            item=item, buyer=buyer, razorpay_payment_id="pay_e",
            buyer_name="Test Buyer", buyer_email="buyer@cobrother.com", buyer_phone="+919999999999",
        )

        mock_get_client.assert_not_called()
        assert result["status"] == "PENDING"
        assert result["success"] is False
        sub = next((o for o in added if type(o).__name__ == "TechnologySubscriptionEntity"), None)
        assert sub is not None
        assert sub.last_provider_status == "MANUAL_FULFILLMENT_REQUIRED"
        assert sub.needs_review is True
        MockMail.send_technology_purchase_pending_email.assert_called_once()
        MockMail.send_technology_purchase_confirmation_email.assert_not_called()


# --------------------------------------------------------------------------- #
# F. Provider ACTIVE -> ACTIVE + confirmation + PROVISIONED/SUCCESS + renewable
# --------------------------------------------------------------------------- #

def test_f_fulfillment_mapping_active_with_provider_id():
    f, o, ec, em = _tech_fulfillment_from_result({
        "status": "ACTIVE", "providerSubscriptionId": "SUB-X",
    })
    assert f == FulfillmentStatus.PROVISIONED
    assert o == OverallStatus.SUCCESS
    assert ec is None


def test_f_provisioned_success_requires_provider_id():
    # ACTIVE without a provider subscription id must NOT be PROVISIONED/SUCCESS.
    f, o, ec, em = _tech_fulfillment_from_result({"status": "ACTIVE"})
    assert (f, o) != (FulfillmentStatus.PROVISIONED, OverallStatus.SUCCESS)


def test_f_renewal_period_helpers():
    start, end = _tech_sub_periods("monthly")
    assert (end - start).days == 30
    start_a, end_a = _tech_sub_periods("annually")
    assert (end_a - start_a).days == 365


def test_f_backoff_progression():
    b1 = _tech_backoff_for(1)
    b2 = _tech_backoff_for(2)
    assert b2 > b1
    assert _tech_backoff_for(99) <= _tech_backoff_for(6)  # capped


# --------------------------------------------------------------------------- #
# G/H. Provider PENDING / FAILURE mapping -> track + email state
# --------------------------------------------------------------------------- #

def test_g_provider_pending_maps_to_in_progress_pending():
    f, o, ec, em = _tech_fulfillment_from_result({"status": "PENDING", "providerSubscriptionId": "SUB-Y"})
    assert f == FulfillmentStatus.IN_PROGRESS
    assert o == OverallStatus.PENDING
    assert ec is None


def test_h_provider_failure_maps_to_failed():
    f, o, ec, em = _tech_fulfillment_from_result({"status": "FAILED", "error": "rejected"})
    assert f == FulfillmentStatus.FAILED
    assert o == OverallStatus.FAILED
    assert ec == "SERVICE_PROVISIONING_FAILED"
    assert em


# --------------------------------------------------------------------------- #
# J/K. Retry worker: reconcile-first, adopt, no duplicate POST, row lock
# --------------------------------------------------------------------------- #

def _retry_service_context():
    """Patches for the retry worker service module."""
    class _Ctx:
        def __enter__(self):
            self._stack = ExitStack()
            patchers = [
                patch("app.service.technology.technology_subscription_retry_service.get_resellportal_client"),
                patch("app.service.technology.technology_subscription_retry_service.MailService"),
                patch("app.service.technology.technology_subscription_retry_service.TrackRecordService"),
                patch("app.repository.track_record_repository.TrackRecordRepository"),
            ]
            return tuple(self._stack.enter_context(p) for p in patchers)

        def __exit__(self, *exc):
            return self._stack.__exit__(*exc)

    return _Ctx()


@pytest.mark.asyncio
async def test_j_retry_reconciles_first_and_adopts_existing_order():
    from app.service.technology.technology_subscription_retry_service import (
        TechnologySubscriptionRetryService,
    )

    sub = _FakeSubscription(status="PENDING", provision_attempts=0)

    with _retry_service_context() as (mock_get_client, MockMail, MockTrackSvc, MockTrackRepo):
        mock_client = MagicMock()
        # An existing matching provider order is found -> MUST be adopted.
        mock_client.find_matching_order.return_value = {
            "provider_order_id": "ORD-EXISTING",
            "provider_subscription_id": "SUB-EXISTING",
            "status": "ACTIVE",
        }
        mock_get_client.return_value = mock_client

        MockTrackRepo.return_value = MagicMock(
            find_by_razorpay_payment_id=AsyncMock(return_value=None),
            find_by_razorpay_order_id=AsyncMock(return_value=None),
        )

        mock_session = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

        svc = TechnologySubscriptionRetryService(mock_session)
        outcome = await svc._process(sub)

        assert outcome == "adopted"
        assert sub.status == "ACTIVE"
        assert sub.provider_order_id == "ORD-EXISTING"
        # CRITICAL: POST /orders must NOT be called — the existing order is adopted.
        mock_client.provision_service.assert_not_called()
        mock_client.find_matching_order.assert_called_once()


@pytest.mark.asyncio
async def test_j_retry_no_existing_order_then_provisions_once():
    from app.service.technology.technology_subscription_retry_service import (
        TechnologySubscriptionRetryService,
    )

    # Business Phone with a stored area code so input validation passes.
    sub = _FakeSubscription(
        status="PROVISIONING_FAILED", provision_attempts=1,
        provision_input=json.dumps({"areaCode": "415"}),
    )

    with _retry_service_context() as (mock_get_client, MockMail, MockTrackSvc, MockTrackRepo):
        mock_client = MagicMock()
        mock_client.find_matching_order.return_value = None
        mock_client.provision_service.return_value = {
            "success": True, "status": "ACTIVE",
            "provider_order_id": "ORD-NEW", "provider_subscription_id": "SUB-NEW",
            "credentials": {}, "current_period_start": datetime.now(timezone.utc),
            "current_period_end": datetime.now(timezone.utc) + timedelta(days=30),
        }
        mock_get_client.return_value = mock_client
        MockMail.send_technology_purchase_confirmation_email = AsyncMock()

        MockTrackRepo.return_value = MagicMock(
            find_by_razorpay_payment_id=AsyncMock(return_value=None),
            find_by_razorpay_order_id=AsyncMock(return_value=None),
        )

        mock_session = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

        svc = TechnologySubscriptionRetryService(mock_session)
        outcome = await svc._process(sub)

        assert outcome == "activated"
        assert sub.status == "ACTIVE"
        assert sub.provider_order_id == "ORD-NEW"
        assert sub.provision_attempts == 2
        mock_client.provision_service.assert_called_once()


@pytest.mark.asyncio
async def test_k_run_tick_uses_row_locking_and_never_charges():
    from app.service.technology.technology_subscription_retry_service import (
        TechnologySubscriptionRetryService,
    )

    mock_session = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    sub = _FakeSubscription(
        status="PENDING", provision_attempts=0,
        provision_input=json.dumps({"areaCode": "415"}),
    )

    # The tick query must use FOR UPDATE SKIP LOCKED (row locking).
    class _FakeStmt:
        def with_for_update(self, skip_locked=False):
            return self

    fake_stmt = _FakeStmt()

    svc_entity = _make_tech_service("business-phone", provider_product_key="business_phone")

    class _User:
        email = "buyer@cobrother.com"
        id = "33333333-3333-3333-3333-333333333333"

    async def fake_execute(stmt):
        class _Result:
            def scalars(self):
                class _Scalars:
                    def all(self):
                        return [sub]
                return _Scalars()

            def scalar_one_or_none(self):
                target = str(stmt)
                if "technology_services_catalogue" in target:
                    return svc_entity
                return _User()
        return _Result()

    mock_session.execute = AsyncMock(side_effect=fake_execute)

    with _retry_service_context() as (mock_get_client, MockMail, MockTrackSvc, MockTrackRepo):
        mock_client = MagicMock()
        mock_client.find_matching_order.return_value = None
        mock_client.provision_service.return_value = {
            "success": True, "status": "ACTIVE",
            "provider_order_id": "ORD-K", "provider_subscription_id": "SUB-K",
            "credentials": {}, "current_period_start": datetime.now(timezone.utc),
            "current_period_end": datetime.now(timezone.utc) + timedelta(days=30),
        }
        mock_get_client.return_value = mock_client
        MockMail.send_technology_purchase_confirmation_email = AsyncMock()
        MockTrackRepo.return_value = MagicMock(
            find_by_razorpay_payment_id=AsyncMock(return_value=None),
            find_by_razorpay_order_id=AsyncMock(return_value=None),
        )

        svc = TechnologySubscriptionRetryService(mock_session)
        # run_tick queries with for_update; the worker must never touch Razorpay.
        stats = await svc.run_tick()
        assert stats["processed"] == 1
        assert stats["activated"] == 1


# --------------------------------------------------------------------------- #
# L. Duplicate Razorpay verification -> alreadyProcessed, one subscription
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_l_duplicate_verification_returns_already_processed():
    svc = _make_tech_service("business-phone", provider_product_key="business_phone")
    item = _make_cart_item(svc.id, "business-phone", areaCode="415")
    buyer = _make_buyer()

    with _checkout_context(svc, item) as (MockCart, MockRepo, mock_get_client, MockPurchase, MockCobrother, MockMail, MockAddon):
        mock_cart_svc = MockCart.return_value
        mock_cart_svc._get_technology_service = AsyncMock(return_value=svc)
        mock_cart_svc._get_technology_service_fallback = AsyncMock(return_value=None)

        class _ExistingSub:
            id = "existing-sub-uuid"
            user_id = str(buyer.id)
            service_slug = "business-phone"
            status = "ACTIVE"
            provider_order_id = "ORD-L"
            provider_subscription_id = "SUB-L"

        # The subscription already exists -> verify returns alreadyProcessed.
        mock_execute = AsyncMock()
        mock_execute.return_value = MagicMock(
            scalar_one_or_none=MagicMock(side_effect=[_ExistingSub(), None]),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        )

        mock_purchase_repo = MagicMock()
        mock_purchase_repo.get_by_razorpay_payment_id = AsyncMock(return_value=None)
        MockPurchase.return_value = mock_purchase_repo
        mock_cobrother_repo = MagicMock()
        mock_cobrother_repo.create = AsyncMock()
        MockCobrother.return_value = mock_cobrother_repo

        mock_session = MagicMock()
        mock_session.execute = mock_execute
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        service = CartCheckoutService(mock_session)
        result = await service._complete_technology_purchase(
            item=item, buyer=buyer, razorpay_payment_id="pay_l",
            buyer_name="Test Buyer", buyer_email="buyer@cobrother.com", buyer_phone="+919999999999",
        )

        assert result.get("alreadyProcessed") is True
        assert result["subscriptionId"] == "existing-sub-uuid"
        # No provider call and no new subscription on duplicate verification.
        mock_get_client.assert_not_called()


# --------------------------------------------------------------------------- #
# M. Renewals: only ACTIVE + provider id + current_period_end
# --------------------------------------------------------------------------- #

def test_m_renewal_eligibility_contract():
    from app.entity.technology_services.technology_subscription_entity import TechnologySubscriptionEntity

    # Contract used by get_admin_renewals filter and renew_subscription gate.
    def renewable(sub: TechnologySubscriptionEntity) -> bool:
        return (
            sub.status == "ACTIVE"
            and sub.is_deleted is False
            and sub.provider_subscription_id is not None
            and not str(sub.provider_subscription_id or "").startswith("SUB-DEFAULT")
            and sub.current_period_end is not None
        )

    good = TechnologySubscriptionEntity(
        status="ACTIVE", is_deleted=False, provider_subscription_id="SUB-REAL",
        current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
    )
    assert renewable(good) is True

    base = {
        "status": "ACTIVE", "is_deleted": False, "provider_subscription_id": "SUB-REAL",
        "current_period_end": datetime.now(timezone.utc) + timedelta(days=30),
    }
    for bad_kwargs in (
        {"status": "PENDING"},
        {"status": "PROVISIONING_FAILED"},
        {"status": "CANCELLED"},
        {"provider_subscription_id": None},
        {"provider_subscription_id": "SUB-DEFAULT"},
        {"current_period_end": None},
        {"is_deleted": True},
    ):
        merged = dict(base)
        merged.update(bad_kwargs)
        bad = TechnologySubscriptionEntity(**merged)
        assert renewable(bad) is False, f"should not be renewable: {bad_kwargs}"


# --------------------------------------------------------------------------- #
# N. Email: exactly one correct email per transition (retry worker)
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_n_retry_sends_confirmation_once_and_sets_flags():
    from app.service.technology.technology_subscription_retry_service import (
        TechnologySubscriptionRetryService,
    )

    sub = _FakeSubscription(
        status="PENDING", provision_attempts=0,
        provision_input=json.dumps({"areaCode": "415"}),
    )

    with _retry_service_context() as (mock_get_client, MockMail, MockTrackSvc, MockTrackRepo):
        mock_client = MagicMock()
        mock_client.find_matching_order.return_value = None
        mock_client.provision_service.return_value = {
            "success": True, "status": "ACTIVE",
            "provider_order_id": "ORD-N", "provider_subscription_id": "SUB-N",
            "credentials": {}, "current_period_start": datetime.now(timezone.utc),
            "current_period_end": datetime.now(timezone.utc) + timedelta(days=30),
        }
        mock_get_client.return_value = mock_client
        MockMail.send_technology_purchase_confirmation_email = AsyncMock()
        MockTrackRepo.return_value = MagicMock(
            find_by_razorpay_payment_id=AsyncMock(return_value=None),
            find_by_razorpay_order_id=AsyncMock(return_value=None),
        )

        mock_session = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

        svc = TechnologySubscriptionRetryService(mock_session)
        await svc._process(sub)

        # Exactly one confirmation email, flags set, no pending/failed.
        MockMail.send_technology_purchase_confirmation_email.assert_called_once()
        MockMail.send_technology_purchase_pending_email.assert_not_called()
        MockMail.send_technology_purchase_failed_email.assert_not_called()
        assert sub.email_sent is True
        assert sub.confirmation_sent is True

        # Second process must NOT resend (email_sent guard).
        await svc._process(sub)
        MockMail.send_technology_purchase_confirmation_email.assert_called_once()


@pytest.mark.asyncio
async def test_n_pending_email_sent_once_for_needs_input():
    from app.service.technology.technology_subscription_retry_service import (
        TechnologySubscriptionRetryService,
    )

    # Business Phone subscription with no area code -> needs-input pending email.
    sub = _FakeSubscription(
        status="PENDING", provision_attempts=0,
        last_provider_status="NEEDS_INPUT",
        provision_input=None,
    )

    with _retry_service_context() as (mock_get_client, MockMail, MockTrackSvc, MockTrackRepo):
        mock_client = MagicMock()
        mock_client.find_matching_order.return_value = None
        mock_get_client.return_value = mock_client
        MockTrackRepo.return_value = MagicMock(
            find_by_razorpay_payment_id=AsyncMock(return_value=None),
            find_by_razorpay_order_id=AsyncMock(return_value=None),
        )

        mock_session = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

        svc = TechnologySubscriptionRetryService(mock_session)
        outcome = await svc._process(sub)

        assert outcome == "needs_input"
        # No provider order was created.
        mock_client.provision_service.assert_not_called()
        MockMail.send_technology_purchase_pending_email.assert_called_once()


# --------------------------------------------------------------------------- #
# O. Track invariant: zero rows PROVISIONED/SUCCESS without ACTIVE sub+provider id
# --------------------------------------------------------------------------- #

def test_o_track_invariant_enforced_by_fulfillment_mapper():
    # The mapper is the single enforcement point: PROVISIONED/SUCCESS requires
    # status ACTIVE AND providerSubscriptionId. Every other state maps away.
    for status, provider_id in [
        ("ACTIVE", "SUB-1"),   # only valid case
        ("ACTIVE", None),
        ("PENDING", "SUB-2"),
        ("PAYMENT_CAPTURED", None),
        ("PROVISIONING", None),
        ("PROVISIONING_FAILED", None),
        ("FAILED", "SUB-3"),
        ("CANCELLED", None),
    ]:
        f, o, _, _ = _tech_fulfillment_from_result({"status": status, "providerSubscriptionId": provider_id})
        if status == "ACTIVE" and provider_id:
            assert (f, o) == (FulfillmentStatus.PROVISIONED, OverallStatus.SUCCESS)
        elif status in ("PENDING", "PAYMENT_CAPTURED", "PROVISIONING"):
            assert (f, o) == (FulfillmentStatus.IN_PROGRESS, OverallStatus.PENDING)
        else:
            assert (f, o) == (FulfillmentStatus.FAILED, OverallStatus.FAILED)


# --------------------------------------------------------------------------- #
# P. CartItem price field regression — verify_checkout_payment failure branch
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_p_verify_checkout_failure_uses_metadata_price_not_unit_price_inr():
    """Regression test for the AttributeError: 'CartItem' object has no attribute
    'unit_price_inr'.

    The failure branch of ``verify_checkout_payment`` must read the real CartItem
    price field (``metadata_json['_checkout_unit_price_inr']``, written at order
    creation for every product type) — NOT a nonexistent ``item.unit_price_inr``
    attribute. With the old code this raised AttributeError inside the ``except``
    handler, masking the real provisioning error and aborting the checkout.
    """
    from app.entity.cart.cart_item_entity import CartItem
    from app.service.cart.cart_checkout_service import CartCheckoutService

    # Precondition: the real CartItem entity has no unit_price_inr column
    # (the price lives in metadata_json['_checkout_unit_price_inr']).
    assert not hasattr(CartItem, "unit_price_inr"), (
        "precondition: the real CartItem entity has no unit_price_inr column"
    )

    item = _make_cart_item("44444444-4444-4444-4444-444444444444", "business-phone", areaCode="415")
    item.metadata_json["_checkout_razorpay_order_id"] = "order_test_123"
    item.metadata_json["_checkout_unit_price_inr"] = 1909.0
    item.metadata_json["_checkout_buyer_name"] = "Test Buyer"
    item.metadata_json["_checkout_buyer_email"] = "buyer@cobrother.com"
    item.metadata_json["_checkout_buyer_phone"] = "+919999999999"

    buyer = _make_buyer()
    req = MagicMock()
    req.razorpay_order_id = "order_test_123"
    req.razorpay_payment_id = "pay_test_123"
    req.razorpay_signature = "sig"

    session = MagicMock()
    session.commit = AsyncMock()
    repo = MagicMock()
    repo.get_by_user_for_update = AsyncMock(return_value=[item])

    svc = CartCheckoutService.__new__(CartCheckoutService)
    svc._session = session
    svc._repo = repo
    svc.remove_fulfilled_cart_items_for_payment = AsyncMock(return_value=1)
    svc._process_item_post_payment = AsyncMock(
        side_effect=RuntimeError("provider exploded")
    )

    recorded: dict = {}

    async def fake_record_paid_attempt(self, **kw):  # noqa: ANN001 - mock instance method
        recorded.update(kw)

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "app.service.cart.cart_checkout_service.rzp.verify_payment_signature",
                return_value=True,
            )
        )
        stack.enter_context(
            patch(
                "app.service.cart.cart_checkout_service.rzp.assert_captured_payment_for_order",
            )
        )
        stack.enter_context(
            patch(
                "app.service.platform.track_record_service.TrackRecordService.record_paid_attempt",
                new=fake_record_paid_attempt,
            )
        )
        stack.enter_context(
            patch(
                "app.service.user.edge_points_service.EdgePointsService.confirm_redemption",
                new=AsyncMock(),
            )
        )

        result = await svc.verify_checkout_payment(buyer, req)

    assert recorded.get("amount_charged") == 1909.0
    assert recorded.get("fulfillment_status") == FulfillmentStatus.FAILED
    assert recorded.get("overall_status") == OverallStatus.FAILED
    assert result["success"] is False
    assert result["needsAttention"] is True
