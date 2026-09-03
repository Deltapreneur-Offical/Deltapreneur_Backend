"""Count one public listing view per authenticated viewer."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.entity.user.app_user import AppUser
from app.repository.domain_listing_view_repository import DomainListingViewRepository
from app.repository.profile_view_repository import ProfileViewRepository
from app.repository.software_view_repository import SoftwareViewRepository
from app.repository.venture_view_repository import VentureViewRepository
from app.repository.virtual_assistant_view_repository import VirtualAssistantViewRepository
from app.repository.operations_service_view_repository import OperationsServiceViewRepository
from app.repository.analytics_repository import AnalyticsRepository
from app.service.analytics.tracking_service import track_software_view, track_venture_view


import time

_view_cooldown_cache = {}
_COOLDOWN_SECONDS = 600

def _clean_cooldown_cache():
    now = time.time()
    keys_to_delete = [k for k, v in _view_cooldown_cache.items() if now - v > _COOLDOWN_SECONDS]
    for k in keys_to_delete:
        del _view_cooldown_cache[k]
def _is_owner(viewer: AppUser | None, owner_user_id: uuid.UUID | None) -> bool:
    return (
        viewer is not None
        and owner_user_id is not None
        and viewer.id == owner_user_id
    )


def _should_count_authenticated_view(
    db: Session,
    *,
    viewer: AppUser | None,
    owner_user_id: uuid.UUID | None,
    has_viewed: Callable[[Session, uuid.UUID, uuid.UUID], bool],
    entity_id: uuid.UUID,
) -> bool:
    """Count at most one view per authenticated viewer (lifetime), with session cooldown."""
    if viewer is None:
        return False
    if _is_owner(viewer, owner_user_id):
        return False

    import random
    if random.random() < 0.05:
        _clean_cooldown_cache()

    now = time.time()
    cache_key = f"auth_view:{entity_id}:{viewer.id}"
    if cache_key in _view_cooldown_cache and now - _view_cooldown_cache[cache_key] < _COOLDOWN_SECONDS:
        return False
    _view_cooldown_cache[cache_key] = now
    return not has_viewed(db, entity_id, viewer.id)


def _should_count_view_with_cooldown(
    db: Session,
    *,
    viewer: AppUser | None,
    client_ip: str | None,
    owner_user_id: uuid.UUID | None,
    has_viewed: Callable[[Session, uuid.UUID, uuid.UUID], bool],
    entity_id: uuid.UUID,
) -> bool:
    if _is_owner(viewer, owner_user_id):
        return False

    import random
    if random.random() < 0.05:
        _clean_cooldown_cache()

    now = time.time()
    if viewer is None:
        if not client_ip:
            return True
        cache_key = f"anon_view:{entity_id}:{client_ip}"
        if cache_key in _view_cooldown_cache and now - _view_cooldown_cache[cache_key] < _COOLDOWN_SECONDS:
            return False
        _view_cooldown_cache[cache_key] = now
        return True
    else:
        cache_key = f"auth_view:{entity_id}:{viewer.id}"
        if cache_key in _view_cooldown_cache and now - _view_cooldown_cache[cache_key] < _COOLDOWN_SECONDS:
            return False
        _view_cooldown_cache[cache_key] = now
        return not has_viewed(db, entity_id, viewer.id)

async def record_domain_listing_view(
    db: Session,
    *,
    listing_id: uuid.UUID,
    owner_user_id: uuid.UUID | None,
    viewer: AppUser | None,
    client_ip: str | None = None,
    viewer_industry: str | None = None,
    viewer_role: str | None = None,
) -> bool:
    if not _should_count_view_with_cooldown(
        db,
        viewer=viewer,
        client_ip=client_ip,
        owner_user_id=owner_user_id,
        has_viewed=DomainListingViewRepository.viewer_has_viewed,
        entity_id=listing_id,
    ):
        return False

    DomainListingViewRepository.create_view(
        db,
        domain_listing_id=listing_id,
        viewer_id=viewer.id if viewer else None,
        viewer_industry=viewer_industry,
        viewer_role=viewer_role,
    )
    return True


async def record_venture_listing_view(
    db: Session,
    *,
    venture_id: uuid.UUID,
    owner_user_id: uuid.UUID | None,
    viewer: AppUser | None,
    viewer_industry: str | None = None,
    viewer_role: str | None = None,
    increment_views: Callable[[], object],
) -> bool:
    if not _should_count_authenticated_view(
        db,
        viewer=viewer,
        owner_user_id=owner_user_id,
        has_viewed=VentureViewRepository.viewer_has_viewed,
        entity_id=venture_id,
    ):
        return False

    await track_venture_view(
        db,
        venture_id=venture_id,
        viewer_id=viewer.id if viewer else None,
        viewer_industry=viewer_industry,
        viewer_role=viewer_role,
    )
    await increment_views()
    return True


async def record_software_listing_view(
    db: Session,
    *,
    software_id: uuid.UUID,
    owner_user_id: uuid.UUID | None,
    viewer: AppUser | None,
    viewer_industry: str | None = None,
    viewer_role: str | None = None,
    increment_views: Callable[[], object],
) -> bool:
    if not _should_count_authenticated_view(
        db,
        viewer=viewer,
        owner_user_id=owner_user_id,
        has_viewed=SoftwareViewRepository.viewer_has_viewed,
        entity_id=software_id,
    ):
        return False

    await track_software_view(
        db,
        software_id=software_id,
        viewer_id=viewer.id if viewer else None,
        viewer_industry=viewer_industry,
        viewer_role=viewer_role,
    )
    await increment_views()
    return True


def record_community_profile_view(
    db: Session,
    *,
    community_id: uuid.UUID,
    owner_user_id: uuid.UUID | None,
    viewer: AppUser | None,
    viewer_industry: str | None = None,
    viewer_role: str | None = None,
    increment_views: Callable[[], object],
) -> bool:
    if viewer is None:
        return False
    if not _should_count_authenticated_view(
        db,
        viewer=viewer,
        owner_user_id=owner_user_id,
        has_viewed=ProfileViewRepository.viewer_has_viewed,
        entity_id=community_id,
    ):
        return False

    AnalyticsRepository.create_profile_view(
        db=db,
        profile_id=community_id,
        viewer_id=viewer.id if viewer else None,
        viewer_industry=viewer_industry,
        viewer_role=viewer_role,
    )
    increment_views()
    return True


def record_virtual_assistant_view(
    db: Session,
    *,
    application_id: uuid.UUID,
    owner_user_id: uuid.UUID | None,
    viewer: AppUser | None,
    client_ip: str | None = None,
    viewer_industry: str | None = None,
    viewer_role: str | None = None,
    increment_views: Callable[[], object],
) -> bool:
    if not _should_count_view_with_cooldown(
        db,
        viewer=viewer,
        client_ip=client_ip,
        owner_user_id=owner_user_id,
        has_viewed=VirtualAssistantViewRepository.viewer_has_viewed,
        entity_id=application_id,
    ):
        return False

    VirtualAssistantViewRepository.create_view(
        db,
        application_id=application_id,
        viewer_id=viewer.id if viewer else None,
        viewer_industry=viewer_industry,
        viewer_role=viewer_role,
    )
    increment_views()
    return True


def record_operations_service_view(
    db: Session,
    *,
    service_id: uuid.UUID,
    viewer: AppUser | None,
    client_ip: str | None = None,
    viewer_industry: str | None = None,
    viewer_role: str | None = None,
) -> bool:
    if not _should_count_view_with_cooldown(
        db,
        viewer=viewer,
        client_ip=client_ip,
        owner_user_id=None,
        has_viewed=OperationsServiceViewRepository.viewer_has_viewed,
        entity_id=service_id,
    ):
        return False

    OperationsServiceViewRepository.create_view(
        db,
        operations_service_id=service_id,
        viewer_id=viewer.id if viewer else None,
        viewer_industry=viewer_industry,
        viewer_role=viewer_role,
    )
    return True
