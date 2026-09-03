"""Roles exempt from auction creation / bid placement fees (not winner payment)."""

from __future__ import annotations

from app.entity.user.user_role import UserRole


def role_waives_auction_platform_fees(role) -> bool:
    """ADMIN and SUPER_ADMIN skip creation + bid placement fees only."""
    if role is None:
        return False
    if role in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        return True
    raw = getattr(role, "value", role)
    text = str(raw or "").upper().replace("ROLE_", "")
    return text in {"ADMIN", "SUPER_ADMIN"}
