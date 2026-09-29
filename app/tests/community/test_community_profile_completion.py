import uuid
from types import SimpleNamespace

from app.utils.community_profile_completion import (
    evaluate_profile_completion,
    is_profile_complete,
    is_profile_complete_simplified,
    is_profile_listable,
)


def _community(**overrides):
    base = {
        "image_url": "https://cdn.example/avatar.jpg",
        "name": "Alex Creator",
        "about": "Hi, I am Alex, a senior React and Python engineer.",
        "role": "FOUNDER",
        "industry": "TECHNOLOGY",
        "skills": "React, Python",
        "location": "Bengaluru",
        "linked_in_id": "linkedin-sub-123",
        "linked_in_profile_url": "https://linkedin.com/in/alex-creator",
        "why_im_here": "Building the next big SaaS.",
        "expected_rate": "400/hr",
        "company_name": "Alex Ventures",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# Legacy-only fields, all empty. Used to build a "simplified-form-only" profile
# (Name + Company Name + LinkedIn URL) so the legacy rule cannot make it listable.
_LEGACY_FIELDS_EMPTY = {
    "about": None,
    "role": None,
    "industry": None,
    "skills": None,
    "location": None,
    "why_im_here": None,
    "expected_rate": None,
}


def test_complete_profile_passes_validation():
    community = _community()
    result = evaluate_profile_completion(community)

    assert result["is_complete"] is True
    assert result["percent"] == 100
    assert result["status"] == "COMPLETE"
    assert result["missing_fields"] == []
    assert is_profile_complete(community) is True


def test_profile_without_image_can_still_be_complete():
    community = _community(image_url=None)
    result = evaluate_profile_completion(community)

    assert result["is_complete"] is True
    assert result["percent"] == 100
    assert is_profile_complete(community) is True


def test_incomplete_profile_lists_missing_fields():
    community = _community(name="", skills="  ", why_im_here=None)
    result = evaluate_profile_completion(community)

    assert result["is_complete"] is False
    assert result["status"] == "INCOMPLETE"
    assert result["percent"] < 100
    missing_fields = {item["field"] for item in result["missing_fields"]}
    assert "name" in missing_fields
    assert "skills" in missing_fields
    assert "why_im_here" in missing_fields
    assert is_profile_complete(community) is False


def test_incomplete_profile_without_expected_rate():
    community = _community(expected_rate=None)
    result = evaluate_profile_completion(community)

    assert result["is_complete"] is False
    missing_fields = {item["field"] for item in result["missing_fields"]}
    assert "expected_rate" in missing_fields


# ── Simplified completion rule (SIMPLIFIED_CREATOR_PROFILE) ──────────────────


def test_simplified_complete_with_only_three_required_fields():
    """Name + company_name + LinkedIn URL suffice; legacy fields may all be empty."""
    community = _community(
        about=None,
        role=None,
        industry=None,
        skills=None,
        location=None,
        why_im_here=None,
        expected_rate=None,
    )

    assert is_profile_complete_simplified(community) is True
    assert is_profile_complete(community) is False  # legacy rule untouched
    assert is_profile_listable(community) is True   # simplified mode is on by default


def test_simplified_incomplete_missing_company_name():
    # Simplified-form-only profile (legacy fields empty) so only the simplified
    # rule is in play; without a company name it is neither complete nor listable.
    community = _community(company_name=None, **_LEGACY_FIELDS_EMPTY)

    assert is_profile_complete_simplified(community) is False
    assert is_profile_listable(community) is False


def test_simplified_incomplete_missing_linkedin_url():
    community = _community(linked_in_profile_url=None, **_LEGACY_FIELDS_EMPTY)

    assert is_profile_complete_simplified(community) is False
    # linked_in_id exists but the simplified rule requires the URL itself.
    assert is_profile_listable(community) is False


def test_legacy_complete_profile_still_listable():
    community = _community(company_name=None)

    assert is_profile_complete(community) is True
    assert is_profile_listable(community) is True


def test_flag_off_restores_legacy_rule(monkeypatch):
    """With SIMPLIFIED_CREATOR_PROFILE=false the old gate is authoritative."""
    from app.core.config import settings

    community = _community(
        about=None,
        role=None,
        industry=None,
        skills=None,
        location=None,
        why_im_here=None,
        expected_rate=None,
    )
    monkeypatch.setattr(settings, "SIMPLIFIED_CREATOR_PROFILE", False)

    assert is_profile_complete_simplified(community) is True
    assert is_profile_listable(community) is False  # falls back to legacy rule
    assert is_profile_complete(community) is False
