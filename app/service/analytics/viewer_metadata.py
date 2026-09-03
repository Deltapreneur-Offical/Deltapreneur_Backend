"""Resolve viewer industry/role metadata for analytics view rows."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.entity.community.community import Community
from app.entity.user.app_user import AppUser


def viewer_analytics_metadata(
    db: Session,
    viewer: AppUser | None,
) -> tuple[str | None, str | None]:
    if viewer is None:
        return None, None

    community = (
        db.query(Community)
        .filter(
            Community.app_user_id == viewer.id,
            Community.is_deleted.is_(False),
        )
        .first()
    )
    industry = community.industry if community else None
    if community and community.role:
        role = community.role
    elif viewer.role:
        role = viewer.role.value if hasattr(viewer.role, "value") else str(viewer.role)
    else:
        role = None
    return industry, role
