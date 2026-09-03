"""Venture GET /{id} public vs owner/admin response shaping."""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.controller.venture import venture_controller
from app.entity.coventure.brand_details_entity import BrandDetails
from app.entity.coventure.contact_info_entity import ContactInfo
from app.entity.coventure.venture_entity import Venture
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.model.venture.venture_response import PublicVentureResponse, VentureResponse
from app.utils.venture_enums import VentureListingApprovalStatus, VentureSaleType


def _venture_with_contact(*, lister: AppUser) -> Venture:
    brand = BrandDetails(brand_name="TestCo")
    brand.id = uuid.uuid4()
    contact = ContactInfo(
        email="secret@example.com",
        phone_number="+919876543210",
    )
    contact.id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    venture = Venture(
        status=True,
        views=1,
        co_venture_application_count=0,
        sale_type=VentureSaleType.REGULAR,
        verified=False,
        gstin_verified=False,
        listing_approval_status=VentureListingApprovalStatus.PENDING_APPROVAL,
        featured=False,
        created_at=now,
        updated_at=now,
    )
    venture.id = uuid.uuid4()
    venture.brand_details = brand
    venture.contact_info = contact
    venture.roles = []
    venture.listed_by = lister
    venture.listed_by_user_id = lister.id
    return venture


def test_anonymous_gets_public_shape() -> None:
    owner = AppUser(email="owner@example.com", role=UserRole.USER)
    owner.id = uuid.uuid4()
    venture = _venture_with_contact(lister=owner)

    result = venture_controller.serialize_venture_detail(venture, None)

    assert isinstance(result, PublicVentureResponse)
    payload = result.model_dump()
    assert "contact_info" not in payload
    listed_by = payload.get("listed_by") or {}
    assert "email" not in listed_by


def test_owner_gets_full_shape() -> None:
    owner = AppUser(email="owner@example.com", role=UserRole.USER)
    owner.id = uuid.uuid4()
    venture = _venture_with_contact(lister=owner)

    result = venture_controller.serialize_venture_detail(venture, owner)

    assert isinstance(result, VentureResponse)
    assert result.contact_info is not None
    assert result.contact_info.email == "secret@example.com"
    assert result.listed_by is not None
    assert result.listed_by.email == "owner@example.com"


def test_admin_gets_full_shape_for_another_users_venture() -> None:
    owner = AppUser(email="owner@example.com", role=UserRole.USER)
    owner.id = uuid.uuid4()
    admin = AppUser(email="admin@example.com", role=UserRole.ADMIN)
    admin.id = uuid.uuid4()
    venture = _venture_with_contact(lister=owner)

    result = venture_controller.serialize_venture_detail(venture, admin)

    assert isinstance(result, VentureResponse)
    assert result.contact_info is not None


def test_other_user_gets_public_shape() -> None:
    owner = AppUser(email="owner@example.com", role=UserRole.USER)
    owner.id = uuid.uuid4()
    other = AppUser(email="other@example.com", role=UserRole.USER)
    other.id = uuid.uuid4()
    venture = _venture_with_contact(lister=owner)

    result = venture_controller.serialize_venture_detail(venture, other)

    assert isinstance(result, PublicVentureResponse)
    assert "contact_info" not in result.model_dump()


def test_blank_website_normalized_to_none() -> None:
    from app.model.venture.venture_request import BrandDetailsRequest

    brand = BrandDetailsRequest(website="   ")
    assert brand.website is None
