import uuid
from types import SimpleNamespace

from app.utils.community_profile_completion import (
    evaluate_profile_completion,
    is_profile_complete,
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
    }
    base.update(overrides)
    return SimpleNamespace(**base)


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
