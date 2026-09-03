"""Tax invoice numbers are allocated only for ACTIVE domain registrations."""

from app.service.domain.tax_invoice_number_service import format_tax_invoice_number
from app.utils.registration_enums import RegistrationOrderStatus


def test_format_tax_invoice_number_uses_two_digit_year():
    assert format_tax_invoice_number(2026, 1) == "AI2600001"
    assert format_tax_invoice_number(2026, 2) == "AI2600002"
    assert format_tax_invoice_number(2026, 10) == "AI2600010"
    assert format_tax_invoice_number(2026, 100) == "AI2600100"
    assert format_tax_invoice_number(2027, 1) == "AI2700001"


def test_parse_tax_invoice_number():
    from app.service.domain.tax_invoice_number_service import parse_tax_invoice_number

    assert parse_tax_invoice_number("AI2600001") == (2026, 1)
    assert parse_tax_invoice_number(" ai2600002 ") == (2026, 2)


def test_failed_statuses_do_not_qualify_for_invoice():
    # Document the contract used by ensure_tax_invoice_number.
    assert RegistrationOrderStatus.PROVISION_FAILED != RegistrationOrderStatus.ACTIVE
    assert RegistrationOrderStatus.REFUNDED != RegistrationOrderStatus.ACTIVE
    assert RegistrationOrderStatus.FAILED != RegistrationOrderStatus.ACTIVE
    assert RegistrationOrderStatus.EXPIRED != RegistrationOrderStatus.ACTIVE
