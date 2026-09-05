"""HubRegistrar registration-success email links and compact layout."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
from app.service.auth.email_templates import (
    HUBREGISTRAR_EMAIL_LOGO_URL,
    HUBREGISTRAR_SOCIAL_FACEBOOK,
    HUBREGISTRAR_SOCIAL_LINKEDIN,
    HUBREGISTRAR_SOCIAL_X,
    domain_registration_active_email_template,
)
from app.service.domain.domain_registration_followup import (
    DomainRegistrationFollowup,
    _order_detail_url,
    hubregistrar_order_detail_url,
    hubregistrar_order_dns_url,
)
from app.utils.registration_enums import RegistrationOrderStatus

TARGET_ORDER_ID = UUID("315e944d-35a7-4e79-ac11-1b3b65da2291")
TARGET_FQDN = "hubregistrar.in"


def _href_for(html: str, label: str) -> str:
    idx = html.find(label)
    assert idx != -1, f"missing button {label!r}"
    href_idx = html.rfind("href=", 0, idx)
    assert href_idx != -1
    start = html.find('"', href_idx) + 1
    end = html.find('"', start)
    return html[start:end]


def test_hubregistrar_urls_are_dynamic_for_order_id(monkeypatch):
    monkeypatch.setattr(
        "app.service.domain.domain_registration_followup.settings.FRONTEND_BASE_URL",
        "",
    )
    other = uuid4()
    assert hubregistrar_order_detail_url(TARGET_ORDER_ID) == (
        f"https://www.deltapreneur.com/storefront/orders/{TARGET_ORDER_ID}"
    )
    assert hubregistrar_order_dns_url(TARGET_ORDER_ID) == (
        f"https://www.deltapreneur.com/storefront/orders/{TARGET_ORDER_ID}#dns"
    )
    assert str(other) in hubregistrar_order_detail_url(other)
    assert str(TARGET_ORDER_ID) not in hubregistrar_order_detail_url(other)


def test_other_emails_still_use_frontend_base_url(monkeypatch):
    monkeypatch.setattr(
        "app.service.domain.domain_registration_followup.settings.FRONTEND_BASE_URL",
        "https://cobrother.com",
    )
    assert _order_detail_url(TARGET_ORDER_ID) == (
        f"https://cobrother.com/storefront/orders/{TARGET_ORDER_ID}"
    )
    assert hubregistrar_order_detail_url(TARGET_ORDER_ID).startswith(
        "https://www.deltapreneur.com/"
    )


def test_active_email_buttons_use_deltapreneur_not_cobrother(monkeypatch):
    monkeypatch.setattr(
        "app.service.domain.domain_registration_followup.settings.FRONTEND_BASE_URL",
        "",
    )
    order_url = hubregistrar_order_detail_url(TARGET_ORDER_ID)
    dns_url = hubregistrar_order_dns_url(TARGET_ORDER_ID)
    html = domain_registration_active_email_template(
        fqdn=TARGET_FQDN,
        order_detail_url=order_url,
        expires_at="2027-08-27T00:00:00+00:00",
        nameservers=["ns1.hubregistrar.com", "ns2.hubregistrar.com", "ns3.hubregistrar.com"],
        manage_dns_url=dns_url,
    )
    view_href = _href_for(html, "View Order")
    manage_href = _href_for(html, "Manage DNS")
    assert view_href == order_url
    assert manage_href == dns_url
    assert "https://www.deltapreneur.com" in view_href
    assert "https://www.deltapreneur.com" in manage_href
    assert str(TARGET_ORDER_ID) in view_href
    assert str(TARGET_ORDER_ID) in manage_href
    assert view_href.endswith(f"/storefront/orders/{TARGET_ORDER_ID}")
    assert manage_href.endswith(f"/storefront/orders/{TARGET_ORDER_ID}#dns")
    assert "cobrother.com" not in view_href.lower()
    assert "cobrother.com" not in manage_href.lower()
    assert "cobrother.com" not in html.lower()
    assert html.lower().find("deltapreneur-logo") < html.lower().find("successfully active")


def test_active_email_cid_logo_uses_deltapreneur():
    html = domain_registration_active_email_template(
        fqdn=TARGET_FQDN,
        order_detail_url=hubregistrar_order_detail_url(TARGET_ORDER_ID),
        expires_at="2027-08-27T00:00:00+00:00",
        nameservers=["ns1.hubregistrar.com"],
        manage_dns_url=hubregistrar_order_dns_url(TARGET_ORDER_ID),
        logo_url="cid:deltapreneur-logo",
    )
    assert 'src="cid:deltapreneur-logo"' in html
    assert "cobrother.com" not in html.lower()


def test_active_email_keeps_confirmation_content():
    html = domain_registration_active_email_template(
        fqdn=TARGET_FQDN,
        order_detail_url=hubregistrar_order_detail_url(TARGET_ORDER_ID),
        expires_at="2027-08-27T00:00:00+00:00",
        nameservers=["ns1.hubregistrar.com"],
        manage_dns_url=hubregistrar_order_dns_url(TARGET_ORDER_ID),
    )
    assert "successfully active" in html
    assert "Your domain is" in html
    assert TARGET_FQDN in html
    assert "27 Aug 2027" in html
    assert "ns1.hubregistrar.com" in html or "ns1&#8203;.hubregistrar&#8203;.com" in html
    assert "Manage DNS" in html
    assert "View Order" in html
    assert "View order &amp; DNS" not in html
    assert "Need help?" in html
    assert "Thank you for choosing Deltapreneur" in html
    assert "The Deltapreneur team" in html
    assert "A7F3D0" not in html
    assert html.find("Need help?") < html.find("Thank you for choosing Deltapreneur")
    help_idx = html.find("Need help?")
    thanks_idx = html.find("Thank you for choosing Deltapreneur")
    assert html[help_idx:thanks_idx].count("<tr>") == 0
    assert 'width="50%"' in html
    assert "Follow us" in html
    assert "DOMAIN" in html
    assert "YOUR NAMESERVERS" in html
    assert "D1FAE5" in html
    assert "background:transparent" in html
    assert HUBREGISTRAR_SOCIAL_FACEBOOK in html
    assert HUBREGISTRAR_SOCIAL_X in html
    assert HUBREGISTRAR_SOCIAL_LINKEDIN in html
    assert "max-width:600px" in html
    assert "deltapreneur-logo" in html
    assert "cid:deltapreneur-logo" not in html
    assert HUBREGISTRAR_EMAIL_LOGO_URL in html
    assert "white-space:nowrap" not in html
    assert "table-layout:fixed" in html
    assert 'width="150"' in html


@pytest.mark.asyncio
async def test_lifecycle_active_email_passes_hubregistrar_urls():
    order = DomainRegistrationOrder(
        id=TARGET_ORDER_ID,
        domain_name="hubregistrar",
        domain_extension=".in",
        buyer_id=uuid4(),
        buyer_email="buyer@example.com",
        period_years=1,
        price_inr=590.0,
        status=RegistrationOrderStatus.ACTIVE,
        razorpay_payment_id="pay_TUlUDOH8WsaJPc",
        email_receipt_sent=True,
        email_submitted_sent=True,
        email_active_sent=False,
        expires_at=datetime(2027, 8, 27, tzinfo=timezone.utc),
    )
    followup = DomainRegistrationFollowup(session=AsyncMock())
    followup._orders = AsyncMock()
    followup._orders.save = AsyncMock()

    with (
        patch(
            "app.service.domain.domain_registration_followup.settings.FRONTEND_BASE_URL",
            "https://cobrother.com",
        ),
        patch(
            "app.service.domain.domain_registration_followup.MailService.send_domain_registration_receipt_email",
            new_callable=AsyncMock,
        ),
        patch(
            "app.service.domain.domain_registration_followup.MailService.send_domain_registration_submitted_email",
            new_callable=AsyncMock,
        ),
        patch(
            "app.service.domain.domain_registration_followup.MailService.send_domain_registration_active_email",
            new_callable=AsyncMock,
        ) as send_active,
    ):
        await followup.send_lifecycle_emails(order)

    send_active.assert_awaited_once()
    kwargs = send_active.await_args.kwargs
    assert kwargs["fqdn"] == TARGET_FQDN
    assert kwargs["order_detail_url"] == (
        f"https://www.deltapreneur.com/storefront/orders/{TARGET_ORDER_ID}"
    )
    assert kwargs["manage_dns_url"] == (
        f"https://www.deltapreneur.com/storefront/orders/{TARGET_ORDER_ID}#dns"
    )
    assert "cobrother.com" not in kwargs["order_detail_url"]
    assert "cobrother.com" not in kwargs["manage_dns_url"]
    assert "hubregistrar.com" not in kwargs["order_detail_url"]
    assert "hubregistrar.com" not in kwargs["manage_dns_url"]
    assert order.email_active_sent is True


def test_active_email_nameservers_never_dump_json_and_stack_vertically():
    blob = (
        '{"hosts": ["ns1.hubregistrar.com", "ns2.hubregistrar.com", '
        '"ns3.hubregistrar.com"], "source": "openprovider", '
        '"syncedAt": "2026-08-28T05:36:19.499322+00:00"}'
    )
    html = domain_registration_active_email_template(
        fqdn=TARGET_FQDN,
        order_detail_url=hubregistrar_order_detail_url(TARGET_ORDER_ID),
        expires_at="2027-08-27T00:00:00+00:00",
        nameservers=blob,  # type: ignore[arg-type]
        manage_dns_url=hubregistrar_order_dns_url(TARGET_ORDER_ID),
    )
    assert "syncedAt" not in html
    assert '"source"' not in html
    assert "openprovider" not in html.lower()
    assert "ns1&#8203;.hubregistrar&#8203;.com" in html
    assert "ns2&#8203;.hubregistrar&#8203;.com" in html
    assert "ns3&#8203;.hubregistrar&#8203;.com" in html
    assert html.count("YOUR NAMESERVERS") == 1
    dict_html = domain_registration_active_email_template(
        fqdn=TARGET_FQDN,
        order_detail_url=hubregistrar_order_detail_url(TARGET_ORDER_ID),
        expires_at="2027-08-27T00:00:00+00:00",
        nameservers={"hosts": ["ns1.hubregistrar.com"], "source": "openprovider"},  # type: ignore[arg-type]
        manage_dns_url=hubregistrar_order_dns_url(TARGET_ORDER_ID),
    )
    assert "ns1&#8203;.hubregistrar&#8203;.com" in dict_html
    assert "syncedAt" not in dict_html
