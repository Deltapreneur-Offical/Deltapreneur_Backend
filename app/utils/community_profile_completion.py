"""Creator (community) profile completeness checks for public marketplace visibility."""

from __future__ import annotations

from typing import Any

from app.entity.community.community import Community

REQUIRED_FIELD_CHECKS: list[tuple[str, str]] = [
    ("name", "Creator name"),
    ("about", "About"),
    ("role", "Role"),
    ("industry", "Industry"),
    ("skills", "Skills"),
    ("location", "Location"),
    ("linked_in_profile_url", "LinkedIn profile link"),
    ("why_im_here", "Bio"),
    ("expected_rate", "Expected Rate"),
]


def _non_empty_str(value: str | None) -> bool:
    return bool((value or "").strip())


def _has_skills(skills: str | None) -> bool:
    if not skills:
        return False
    return any(part.strip() for part in skills.split(","))


def _field_complete(community: Community, field: str) -> bool:
    if field == "name":
        return _non_empty_str(getattr(community, "name", None))
    if field == "about":
        return _non_empty_str(getattr(community, "about", None))
    if field == "role":
        return _non_empty_str(getattr(community, "role", None))
    if field == "industry":
        return _non_empty_str(getattr(community, "industry", None))
    if field == "skills":
        return _has_skills(getattr(community, "skills", None))
    if field == "location":
        return _non_empty_str(getattr(community, "location", None))
    if field == "linked_in_id":
        return _non_empty_str(getattr(community, "linked_in_id", None))
    if field == "linked_in_profile_url":
        return _non_empty_str(getattr(community, "linked_in_profile_url", None))
    if field == "why_im_here":
        return _non_empty_str(getattr(community, "why_im_here", None))
    if field == "expected_rate":
        return _non_empty_str(getattr(community, "expected_rate", None))
    return False


def evaluate_profile_completion(community: Community) -> dict[str, Any]:
    total = len(REQUIRED_FIELD_CHECKS)
    missing: list[dict[str, str]] = []
    completed = 0

    for field_key, label in REQUIRED_FIELD_CHECKS:
        if _field_complete(community, field_key):
            completed += 1
        else:
            missing.append({"field": field_key, "label": label})

    percent = round((completed / total) * 100) if total else 0
    is_complete = completed == total

    return {
        "is_complete": is_complete,
        "percent": percent,
        "missing_fields": missing,
        "status": "COMPLETE" if is_complete else "INCOMPLETE",
    }


BASIC_REQUIRED_FIELDS: list[str] = [
    "name",
    "role",
    "industry",
    "skills",
    "location",
    "linked_in_id",
    "why_im_here",
    "expected_rate",
]


def is_profile_complete(community: Community) -> bool:
    return all(_field_complete(community, field) for field in BASIC_REQUIRED_FIELDS)
