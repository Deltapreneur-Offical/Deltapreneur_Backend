"""Venture response privacy tests."""

import uuid
from datetime import datetime, timezone

from app.entity.coventure.agreement_entity import Agreement
from app.entity.coventure.brand_details_entity import BrandDetails
from app.entity.coventure.contact_info_entity import ContactInfo
from app.entity.coventure.venture_entity import Venture
from app.entity.user.app_user import AppUser
from app.model.user.public_user import to_owner_user, to_public_user
from app.model.venture.venture_response import (
    serialize_owner_venture,
    serialize_public_venture,
)
from app.utils.venture_enums import VentureListingApprovalStatus, VentureSaleType


def _build_venture_entity(*, lister: AppUser):
    """Minimal venture graph for serializer tests (no DB)."""
    brand = BrandDetails(brand_name="TestCo")
    brand.id = uuid.uuid4()
    contact = ContactInfo(
        email="listing@public.example.com",
        phone_number="+919876543210",
    )
    contact.id = uuid.uuid4()
    agreement = Agreement(terms=True)
    agreement.id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    venture = Venture(
        status=True,
        views=0,
        co_venture_application_count=0,
        sale_type=VentureSaleType.REGULAR,
        current_problem="problem",
        gstin_verified=True,
        gstin_legal_name="Secret Legal Name Pvt Ltd",
        listing_approval_status=VentureListingApprovalStatus.APPROVED,
        verified=False,
        featured=False,
        created_at=now,
        updated_at=now,
    )
    venture.id = uuid.uuid4()
    venture.brand_details = brand
    venture.contact_info = contact
    venture.agreement = agreement
    venture.roles = []
    venture.listed_by = lister
    venture.listed_by_user_id = lister.id
    return venture


def test_public_listed_by_hides_account_email() -> None:
    owner = AppUser(
        email="owner@secret.com",
        firstname="Ada",
        lastname="Lovelace",
        username="ada",
    )
    owner.id = uuid.uuid4()

    public = to_public_user(owner)
    payload = public.model_dump()
    assert "email" not in payload
    assert "display_name" not in payload
    assert payload["firstname"] == "Ada"
    assert payload["lastname"] == "Lovelace"
    assert payload["username"] == "Ada Lovelace"


def test_owner_listed_by_includes_email() -> None:
    owner = AppUser(
        email="owner@secret.com",
        firstname="Ada",
        lastname="Lovelace",
        username="ada",
    )
    owner.id = uuid.uuid4()

    owner_view = to_owner_user(owner)
    assert owner_view.email == "owner@secret.com"
    assert owner_view.firstname == "Ada"
    assert owner_view.lastname == "Lovelace"


def test_serialize_public_venture_omits_sensitive_fields() -> None:
    owner = AppUser(
        email="owner@secret.com",
        firstname="Ada",
        lastname="Lovelace",
    )
    owner.id = uuid.uuid4()
    venture = _build_venture_entity(lister=owner)

    public = serialize_public_venture(venture)
    payload = public.model_dump()

    assert "contact_info" not in payload
    assert "agreement" not in payload
    assert "gstin_legal_name" not in payload
    assert payload["listed_by"]["firstname"] == "Ada"
    assert payload["listed_by"]["lastname"] == "Lovelace"
    assert "email" not in payload["listed_by"]
    assert "display_name" not in payload["listed_by"]


def test_serialize_owner_venture_includes_contact_and_agreement() -> None:
    owner = AppUser(email="owner@secret.com", username="owner")
    owner.id = uuid.uuid4()
    venture = _build_venture_entity(lister=owner)

    owner_resp = serialize_owner_venture(venture)
    payload = owner_resp.model_dump()

    assert payload["contact_info"]["email"] == "listing@public.example.com"
    assert payload["agreement"]["terms"] is True
    assert payload["listed_by"]["email"] == "owner@secret.com"
    assert "display_name" not in payload["listed_by"]


def test_serialize_owner_venture_uses_lister_fallback() -> None:
    owner = AppUser(
        email="owner@secret.com",
        firstname="Ada",
        lastname="Lovelace",
    )
    owner.id = uuid.uuid4()
    venture = _build_venture_entity(lister=owner)
    venture.listed_by = None

    owner_resp = serialize_owner_venture(venture, lister=owner)
    assert owner_resp.listed_by is not None
    assert owner_resp.listed_by.email == "owner@secret.com"
    assert owner_resp.listed_by.firstname == "Ada"
