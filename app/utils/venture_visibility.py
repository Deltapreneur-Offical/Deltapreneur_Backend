"""Shared venture and auction visibility predicates."""

from __future__ import annotations

import uuid

from app.entity.coventure.venture_entity import Venture
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole
from app.utils.venture_enums import (
    VentureAcquisitionApplicationStatus,
    VentureListingApprovalStatus,
)

ACTIVE_ACQUISITION_STATUSES = frozenset({
    VentureAcquisitionApplicationStatus.PENDING,
    VentureAcquisitionApplicationStatus.SELLER_ACCEPTED,
})


def is_admin_user(viewer: AppUser | None) -> bool:
    return viewer is not None and viewer.role == UserRole.ADMIN


def is_venture_listing_approved(venture: Venture) -> bool:
    return (
        not venture.is_deleted
        and not venture.taken_down
        and venture.status
        and venture.listing_approval_status == VentureListingApprovalStatus.APPROVED
    )


def viewer_is_venture_owner(venture: Venture, viewer: AppUser | None) -> bool:
    return (
        viewer is not None
        and venture.listed_by_user_id is not None
        and venture.listed_by_user_id == viewer.id
    )


def can_view_venture_listing(
    venture: Venture,
    viewer: AppUser | None,
    *,
    active_applicant_user_id: uuid.UUID | None = None,
) -> bool:
    if is_venture_listing_approved(venture):
        return True
    if viewer is None:
        return False
    if is_admin_user(viewer) or viewer_is_venture_owner(venture, viewer):
        return True
    if active_applicant_user_id is not None and viewer.id == active_applicant_user_id:
        return True
    return False
