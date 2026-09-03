"""Tests for post-registration follow-up (sync, emails idempotency)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

def _mock_openprovider_settings() -> MagicMock:
    cfg = MagicMock()
    cfg.domain_registrar.return_value = "openprovider"
    return cfg
from uuid import uuid4

import pytest

from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
from app.service.domain.domain_registration_followup import (
    DomainRegistrationFollowup,
    build_domain_management,
    should_send_registration_failed_email,
)
from app.utils.registration_enums import RegistrationOrderStatus


def _order(**kwargs) -> DomainRegistrationOrder:
    o = DomainRegistrationOrder(
        id=uuid4(),
        domain_name="brand",
        domain_extension=".com",
        buyer_id=uuid4(),
        buyer_email="buyer@example.com",
        period_years=1,
        price_inr=999.0,
        status=RegistrationOrderStatus.REGISTRATION_PENDING,
        open_provider_domain_id="12345",
    )
    for k, v in kwargs.items():
        setattr(o, k, v)
    return o


@pytest.mark.asyncio
async def test_sync_promotes_to_active():
    order = _order()
    mock_orders = AsyncMock()
    mock_orders.save = AsyncMock()

    followup = DomainRegistrationFollowup(session=AsyncMock())
    followup._orders = mock_orders

    details = {
        "orderid": "12345",
        "domainname": "brand.com",
        "currentstatus": "Active",
        "raaVerificationStatus": "Pending",
        "endtime": int(datetime(2027, 1, 1, tzinfo=timezone.utc).timestamp()),
    }

    with (
        patch(
            "app.service.domain.domain_registration_followup.settings",
            _mock_openprovider_settings(),
        ),
        patch(
            "app.integrations.openprovider.client.get_domain_all_details",
            AsyncMock(return_value=details),
        ),
        patch(
            "app.integrations.openprovider.client.is_registration_confirmed",
            return_value=True,
        ),
        patch(
            "app.integrations.openprovider.client.is_configured",
            return_value=True,
        ),
        patch(
            "app.integrations.openprovider.client.parse_raa_verification_status",
            return_value="PENDING",
        ),
        patch(
            "app.integrations.openprovider.client.parse_expiry_from_details",
            return_value=datetime(2027, 1, 1, tzinfo=timezone.utc),
        ),
    ):
        confirmed, updated = await followup.sync_from_registrar(order)

    assert confirmed is True
    assert updated.status == RegistrationOrderStatus.ACTIVE
    assert updated.icann_verification_status == "PENDING"


@pytest.mark.asyncio
async def test_sync_transfer_promotes_to_active_and_completed():
    """A transfer confirmed by OpenProvider becomes ACTIVE + transfer COMPLETED.

    This is the authoritative state the frontend needs: transferStatus must be
    COMPLETED (not PENDING) or the order page keeps showing TRANSFER PENDING
    with DNS / Email & Security locked even though the transfer finished.
    """
    order = _order(transfer_status="PENDING")
    mock_orders = AsyncMock()
    mock_orders.save = AsyncMock()

    followup = DomainRegistrationFollowup(session=AsyncMock())
    followup._orders = mock_orders

    details = {
        "orderid": "12345",
        "domainname": "brand.com",
        "currentstatus": "Active",
        "raaVerificationStatus": "Pending",
        "endtime": int(datetime(2027, 1, 1, tzinfo=timezone.utc).timestamp()),
    }

    with (
        patch(
            "app.service.domain.domain_registration_followup.settings",
            _mock_openprovider_settings(),
        ),
        patch(
            "app.integrations.openprovider.client.get_domain_all_details",
            AsyncMock(return_value=details),
        ),
        patch(
            "app.integrations.openprovider.client.is_registration_confirmed",
            return_value=True,
        ),
        patch(
            "app.integrations.openprovider.client.is_configured",
            return_value=True,
        ),
        patch(
            "app.integrations.openprovider.client.parse_raa_verification_status",
            return_value="PENDING",
        ),
        patch(
            "app.integrations.openprovider.client.parse_expiry_from_details",
            return_value=datetime(2027, 1, 1, tzinfo=timezone.utc),
        ),
    ):
        confirmed, updated = await followup.sync_from_registrar(order)

    assert confirmed is True
    assert updated.status == RegistrationOrderStatus.ACTIVE
    assert updated.transfer_status == "COMPLETED"
    assert updated.provision_message == "Domain transfer completed successfully"


@pytest.mark.asyncio
async def test_sync_transfer_already_active_updates_stale_pending():
    """A transfer already ACTIVE in DB but with stale transfer_status=PENDING
    (the drygrain.com scenario) must be corrected to COMPLETED on sync."""
    order = _order(
        status=RegistrationOrderStatus.ACTIVE,
        transfer_status="PENDING",
        completed_at=datetime(2026, 8, 17, 14, 4, tzinfo=timezone.utc),
    )
    mock_orders = AsyncMock()
    mock_orders.save = AsyncMock()

    followup = DomainRegistrationFollowup(session=AsyncMock())
    followup._orders = mock_orders

    details = {
        "orderid": "12345",
        "domainname": "brand.com",
        "currentstatus": "Active",
    }

    with (
        patch(
            "app.service.domain.domain_registration_followup.settings",
            _mock_openprovider_settings(),
        ),
        patch(
            "app.integrations.openprovider.client.get_domain_all_details",
            AsyncMock(return_value=details),
        ),
        patch(
            "app.integrations.openprovider.client.is_registration_confirmed",
            return_value=True,
        ),
        patch(
            "app.integrations.openprovider.client.is_configured",
            return_value=True,
        ),
        patch(
            "app.integrations.openprovider.client.parse_raa_verification_status",
            return_value="PENDING",
        ),
        patch(
            "app.integrations.openprovider.client.parse_expiry_from_details",
            return_value=None,
        ),
    ):
        confirmed, updated = await followup.sync_from_registrar(order)

    assert confirmed is True
    assert updated.status == RegistrationOrderStatus.ACTIVE
    assert updated.transfer_status == "COMPLETED"
    # completed_at must not be overwritten when the order is already active
    assert updated.completed_at == datetime(2026, 8, 17, 14, 4, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_sync_transfer_pending_stays_pending():
    """An in-progress OpenProvider transfer must stay PENDING and locked."""
    order = _order(transfer_status="PENDING")
    mock_orders = AsyncMock()
    mock_orders.save = AsyncMock()

    followup = DomainRegistrationFollowup(session=AsyncMock())
    followup._orders = mock_orders

    details = {
        "orderid": "12345",
        "domainname": "brand.com",
        "currentstatus": "TRN",
    }

    with (
        patch(
            "app.service.domain.domain_registration_followup.settings",
            _mock_openprovider_settings(),
        ),
        patch(
            "app.integrations.openprovider.client.get_domain_all_details",
            AsyncMock(return_value=details),
        ),
        patch(
            "app.integrations.openprovider.client.is_registration_confirmed",
            return_value=False,
        ),
        patch(
            "app.integrations.openprovider.client.is_configured",
            return_value=True,
        ),
        patch(
            "app.integrations.openprovider.client.parse_raa_verification_status",
            return_value="UNKNOWN",
        ),
        patch(
            "app.integrations.openprovider.client.parse_expiry_from_details",
            return_value=None,
        ),
    ):
        confirmed, updated = await followup.sync_from_registrar(order)

    assert confirmed is False
    assert updated.status == RegistrationOrderStatus.REGISTRATION_PENDING
    assert updated.transfer_status == "PENDING"


@pytest.mark.asyncio
async def test_sync_registration_confirmed_keeps_registration_message():
    """Plain registrations keep the standard confirmation message and their
    transfer_status (NONE) is never touched."""
    order = _order()
    mock_orders = AsyncMock()
    mock_orders.save = AsyncMock()

    followup = DomainRegistrationFollowup(session=AsyncMock())
    followup._orders = mock_orders

    details = {
        "orderid": "12345",
        "domainname": "brand.com",
        "currentstatus": "Active",
    }

    with (
        patch(
            "app.service.domain.domain_registration_followup.settings",
            _mock_openprovider_settings(),
        ),
        patch(
            "app.integrations.openprovider.client.get_domain_all_details",
            AsyncMock(return_value=details),
        ),
        patch(
            "app.integrations.openprovider.client.is_registration_confirmed",
            return_value=True,
        ),
        patch(
            "app.integrations.openprovider.client.is_configured",
            return_value=True,
        ),
        patch(
            "app.integrations.openprovider.client.parse_raa_verification_status",
            return_value="PENDING",
        ),
        patch(
            "app.integrations.openprovider.client.parse_expiry_from_details",
            return_value=None,
        ),
    ):
        confirmed, updated = await followup.sync_from_registrar(order)

    assert confirmed is True
    assert updated.status == RegistrationOrderStatus.ACTIVE
    assert updated.transfer_status in (None, "NONE")
    assert updated.provision_message == "Domain registration confirmed with registrar"


@pytest.mark.asyncio
async def test_receipt_email_sent_once():
    order = _order(
        status=RegistrationOrderStatus.PAYMENT_COMPLETED,
        razorpay_payment_id="pay_1",
        email_receipt_sent=False,
    )
    mock_orders = AsyncMock()
    mock_orders.save = AsyncMock()

    followup = DomainRegistrationFollowup(session=AsyncMock())
    followup._orders = mock_orders

    with patch(
        "app.service.domain.domain_registration_followup.MailService.send_domain_registration_receipt_email",
        AsyncMock(),
    ) as send_mock:
        await followup.send_lifecycle_emails(order)
        await followup.send_lifecycle_emails(order)

    assert send_mock.await_count == 1
    assert order.email_receipt_sent is True


def test_build_domain_management_active_order():
    order = _order(
        status=RegistrationOrderStatus.ACTIVE,
        registration_confirmed=True,
        razorpay_payment_id="pay_test_123",
        nameservers=["ns1.example.com", "ns2.example.com"],
    )
    mgmt = build_domain_management(order)
    assert mgmt["available"] is True
    assert mgmt["domain"] == "brand.com"
    assert mgmt["loginEmail"] == "buyer@example.com"
    assert len(mgmt["nameservers"]) >= 2
    assert "customerPanelUrl" in mgmt
    assert mgmt["customerPanelUrl"] is not None
    assert "openprovider" not in (mgmt["customerPanelUrl"] or "").lower()
    assert "#dns" in (mgmt["customerPanelUrl"] or "")
    assert mgmt.get("cobrotherDnsUrl") == mgmt["customerPanelUrl"]
    assert mgmt.get("registrarControlPanelUrl") is None
    assert mgmt["dnsSteps"]
    assert all("openprovider" not in s.lower() for s in mgmt["dnsSteps"])


def test_build_domain_management_unavailable_before_active():
    order = _order(status=RegistrationOrderStatus.CREATED)
    mgmt = build_domain_management(order)
    assert mgmt["available"] is False
    assert mgmt.get("customerPanelUrl") is None
    assert mgmt.get("cobrotherDnsUrl") is None


@pytest.mark.asyncio
async def test_recover_stale_pending_marks_failed_when_op_unconfirmed():
    from datetime import timedelta

    past = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    stale = _order(
        status=RegistrationOrderStatus.REGISTRATION_PENDING,
        open_provider_domain_id="999",
        provision_message=f"PENDING_SINCE:{past}|waiting",
        updated_at=datetime.now(timezone.utc),
    )
    mock_orders = AsyncMock()
    mock_orders.list_open_pending = AsyncMock(return_value=[stale])
    mock_orders.save = AsyncMock()
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    followup = DomainRegistrationFollowup(session=mock_session)
    followup._orders = mock_orders
    followup.sync_from_registrar = AsyncMock(return_value=(False, stale))
    followup.send_lifecycle_emails = AsyncMock()

    with patch(
        "app.service.domain.domain_registration_followup.settings"
    ) as mock_settings:
        mock_settings.DOMAIN_REGISTRATION_PENDING_TIMEOUT_MINUTES = 10.0
        stats = await followup.recover_stale_registration_pending()

    assert stats["examined"] == 1
    assert stats["failed"] == 1
    assert stale.status == RegistrationOrderStatus.PROVISION_FAILED
    assert "stale-pending recovery" in (stale.provision_message or "")
    mock_session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_recover_stale_pending_no_op_id_fails_after_retry():
    from datetime import timedelta

    past = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    stale = _order(
        status=RegistrationOrderStatus.PAYMENT_COMPLETED,
        open_provider_domain_id=None,
        provision_message=f"PENDING_SINCE:{past}",
    )
    mock_orders = AsyncMock()
    mock_orders.list_open_pending = AsyncMock(return_value=[stale])
    mock_orders.get_by_id = AsyncMock(return_value=stale)
    mock_orders.save = AsyncMock()
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    followup = DomainRegistrationFollowup(session=mock_session)
    followup._orders = mock_orders
    followup.send_lifecycle_emails = AsyncMock()
    followup._retry_provision = AsyncMock()

    with patch(
        "app.service.domain.domain_registration_followup.settings"
    ) as mock_settings:
        mock_settings.DOMAIN_REGISTRATION_PENDING_TIMEOUT_MINUTES = 10.0
        stats = await followup.recover_stale_registration_pending()

    assert stats["retried"] == 1
    assert stats["failed"] == 1
    assert stale.status == RegistrationOrderStatus.PROVISION_FAILED


@pytest.mark.asyncio
async def test_recover_stale_pending_defers_when_retry_gets_op_id():
    from datetime import timedelta

    past = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    stale = _order(
        status=RegistrationOrderStatus.PAYMENT_COMPLETED,
        open_provider_domain_id=None,
        provision_message=f"PENDING_SINCE:{past}",
    )

    async def _provision(_order):
        stale.open_provider_domain_id = "777"
        stale.status = RegistrationOrderStatus.REGISTRATION_PENDING

    mock_orders = AsyncMock()
    mock_orders.list_open_pending = AsyncMock(return_value=[stale])
    mock_orders.get_by_id = AsyncMock(return_value=stale)
    mock_orders.save = AsyncMock()
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    followup = DomainRegistrationFollowup(session=mock_session)
    followup._orders = mock_orders
    followup.sync_from_registrar = AsyncMock(return_value=(False, stale))
    followup.send_lifecycle_emails = AsyncMock()
    followup._retry_provision = AsyncMock(side_effect=_provision)

    with patch(
        "app.service.domain.domain_registration_followup.settings"
    ) as mock_settings:
        mock_settings.DOMAIN_REGISTRATION_PENDING_TIMEOUT_MINUTES = 10.0
        stats = await followup.recover_stale_registration_pending()

    assert stats["deferred_pending"] == 1
    assert stats["failed"] == 0
    assert stale.status == RegistrationOrderStatus.REGISTRATION_PENDING
    assert stale.open_provider_domain_id == "777"


def test_failure_email_skipped_for_domain_not_free_race():
    order = _order(
        status=RegistrationOrderStatus.PROVISION_FAILED,
        razorpay_payment_id="pay_1",
        provision_message="Domain no longer available at registrar",
        email_failed_sent=False,
        email_active_sent=False,
    )
    assert should_send_registration_failed_email(order) is False


def test_failure_email_skipped_when_active_email_already_sent():
    order = _order(
        status=RegistrationOrderStatus.PROVISION_FAILED,
        razorpay_payment_id="pay_1",
        provision_message="OpenProvider rejected the request",
        email_failed_sent=False,
        email_active_sent=True,
    )
    assert should_send_registration_failed_email(order) is False


def test_failure_email_sent_for_genuine_terminal_failure():
    order = _order(
        status=RegistrationOrderStatus.PROVISION_FAILED,
        razorpay_payment_id="pay_1",
        provision_message="Registration stuck without OpenProvider domain id",
        email_failed_sent=False,
        email_active_sent=False,
    )
    assert should_send_registration_failed_email(order) is True


@pytest.mark.asyncio
async def test_lifecycle_does_not_send_failed_email_for_not_free_race():
    order = _order(
        status=RegistrationOrderStatus.PROVISION_FAILED,
        razorpay_payment_id="pay_1",
        provision_message="Domain no longer available at registrar",
        email_failed_sent=False,
        email_active_sent=True,
        email_receipt_sent=True,
    )
    mock_orders = AsyncMock()
    mock_orders.save = AsyncMock()
    followup = DomainRegistrationFollowup(session=AsyncMock())
    followup._orders = mock_orders

    with patch(
        "app.service.domain.domain_registration_followup.MailService.send_domain_registration_failed_email",
        AsyncMock(),
    ) as send_failed:
        await followup.send_lifecycle_emails(order)

@pytest.mark.asyncio
async def test_lifecycle_sends_failed_email_only_for_genuine_terminal_failure():
    order = _order(
        status=RegistrationOrderStatus.PROVISION_FAILED,
        razorpay_payment_id="pay_1",
        provision_message="Registration stuck without OpenProvider domain id",
        email_failed_sent=False,
        email_active_sent=False,
        email_receipt_sent=True,
    )
    mock_orders = AsyncMock()
    mock_orders.save = AsyncMock()
    followup = DomainRegistrationFollowup(session=AsyncMock())
    followup._orders = mock_orders

    with patch(
        "app.service.domain.domain_registration_followup.MailService.send_domain_registration_failed_email",
        AsyncMock(),
    ) as send_failed:
        await followup.send_lifecycle_emails(order)

    send_failed.assert_awaited_once()
    assert order.email_failed_sent is True