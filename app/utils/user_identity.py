"""User display identity helpers."""

from __future__ import annotations

from app.entity.user.app_user import AppUser


def resolved_username(user: AppUser) -> str | None:
    """Display username: firstname + lastname when both are set, else stored username."""
    parts = [
        p.strip()
        for p in (user.firstname, user.lastname)
        if p and str(p).strip()
    ]
    if parts:
        return " ".join(parts)
    stored = (user.username or "").strip()
    return stored or None
