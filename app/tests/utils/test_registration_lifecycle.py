"""Lifecycle status mapping for storefront."""

from uuid import uuid4

from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
from app.utils.registration_enums import RegistrationOrderStatus
from app.utils.registration_lifecycle import registration_lifecycle_status


def _order(status: RegistrationOrderStatus) -> DomainRegistrationOrder:
    return DomainRegistrationOrder(
        id=uuid4(),
        domain_name="x",
        domain_extension=".com",
        buyer_id=uuid4(),
        period_years=1,
        price_inr=1.0,
        status=status,
    )


def test_lifecycle_payment_success():
    assert registration_lifecycle_status(_order(RegistrationOrderStatus.PAYMENT_COMPLETED)) == "payment_success"


def test_lifecycle_registration_pending():
    assert (
        registration_lifecycle_status(_order(RegistrationOrderStatus.REGISTRATION_PENDING))
        == "registration_pending"
    )


def test_lifecycle_registration_confirmed():
    assert registration_lifecycle_status(_order(RegistrationOrderStatus.ACTIVE)) == "registration_confirmed"


def test_lifecycle_checkout_cancelled_from_created_message():
    order = _order(RegistrationOrderStatus.CREATED)
    order.provision_message = "Checkout cancelled before payment; pending registration order expired."
    assert registration_lifecycle_status(order) == "checkout_cancelled"
