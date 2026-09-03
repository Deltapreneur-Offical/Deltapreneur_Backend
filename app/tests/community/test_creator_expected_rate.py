from types import SimpleNamespace

import pytest

from app.model.community.community_update_request import CommunityUpdateRequest
from app.service.community.community_service import CommunityService


def test_update_request_trims_expected_rate():
    request = CommunityUpdateRequest(expectedRate="  4000/day  ")
    assert request.expected_rate == "4000/day"


def test_update_request_empty_expected_rate_becomes_none():
    request = CommunityUpdateRequest(expectedRate="   ")
    assert request.expected_rate is None


def test_update_request_accepts_new_creator_fields():
    request = CommunityUpdateRequest(
        introductionVideoLink="https://www.youtube.com/watch?v=abc123",
        resumeDriveLink="https://drive.google.com/file/d/abc123/view",
        portfolioWebsiteLink="https://portfolio.example.com",
        preferredWorkType="  FULL_TIME  ",
        industryExpertise="  AI, FinTech  ",
        languagesKnown="  English, Hindi  ",
    )
    assert request.introduction_video_link == "https://www.youtube.com/watch?v=abc123"
    assert request.resume_drive_link == "https://drive.google.com/file/d/abc123/view"
    assert request.portfolio_website_link == "https://portfolio.example.com"
    assert request.preferred_work_type == "FULL_TIME"
    assert request.industry_expertise == "AI, FinTech"
    assert request.languages_known == "English, Hindi"


def test_to_response_includes_expected_rate_camel_case():
    community = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        linked_in_id="li-1",
        name="Alex",
        image_url=None,
        linked_in_profile_url=None,
        role="FOUNDER",
        views=0,
        skills="React",
        industry="TECHNOLOGY",
        location="Bengaluru",
        why_im_here="Building products.",
        expected_rate="400/hr",
        is_approved=True,
        app_user_id="00000000-0000-0000-0000-000000000002",
        created_at=None,
        updated_at=None,
    )
    payload = CommunityService._to_response(community)

    assert payload["expected_rate"] == "400/hr"
    assert payload["expectedRate"] == "400/hr"


def test_to_response_null_expected_rate():
    community = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        linked_in_id="li-1",
        name="Alex",
        image_url=None,
        linked_in_profile_url=None,
        role="FOUNDER",
        views=0,
        skills="React",
        industry="TECHNOLOGY",
        location="Bengaluru",
        why_im_here="Building products.",
        expected_rate=None,
        is_approved=True,
        app_user_id="00000000-0000-0000-0000-000000000002",
        created_at=None,
        updated_at=None,
    )
    payload = CommunityService._to_response(community)

    assert payload["expected_rate"] is None
    assert payload["expectedRate"] is None


def test_to_response_includes_new_creator_fields():
    community = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        linked_in_id="li-1",
        name="Alex",
        image_url=None,
        cover_image_url=None,
        linked_in_profile_url=None,
        role="FOUNDER",
        views=0,
        skills="React",
        industry="TECHNOLOGY",
        location="Bengaluru",
        why_im_here="Building products.",
        expected_rate="400/hr",
        introduction_video_link="https://www.youtube.com/watch?v=abc123",
        resume_drive_link="https://drive.google.com/file/d/abc123/view",
        portfolio_website_link="https://portfolio.example.com",
        preferred_work_type="FULL_TIME",
        industry_expertise="AI, FinTech",
        languages_known="English, Hindi",
        is_approved=True,
        featured=False,
        app_user_id="00000000-0000-0000-0000-000000000002",
        created_at=None,
        updated_at=None,
    )
    payload = CommunityService._to_response(community)

    assert payload["introduction_video_link"] == "https://www.youtube.com/watch?v=abc123"
    assert payload["resume_drive_link"] == "https://drive.google.com/file/d/abc123/view"
    assert payload["portfolio_website_link"] == "https://portfolio.example.com"
    assert payload["preferred_work_type"] == "FULL_TIME"
    assert payload["industry_expertise"] == "AI, FinTech"
    assert payload["languages_known"] == "English, Hindi"
    assert payload["introductionVideoLink"] == "https://www.youtube.com/watch?v=abc123"
    assert payload["resumeDriveLink"] == "https://drive.google.com/file/d/abc123/view"
    assert payload["portfolioWebsiteLink"] == "https://portfolio.example.com"
    assert payload["preferredWorkType"] == "FULL_TIME"
    assert payload["industryExpertise"] == "AI, FinTech"
    assert payload["languagesKnown"] == "English, Hindi"


def test_update_request_accepts_urls_without_scheme():
    request = CommunityUpdateRequest(
        introductionVideoLink="www.youtube.com/watch?v=abc123",
        portfolioWebsiteLink="portfolio.example.com",
    )
    assert request.introduction_video_link == "https://www.youtube.com/watch?v=abc123"
    assert request.portfolio_website_link == "https://portfolio.example.com"


def test_resolve_media_url_local_rewrites():
    from app.integrations.s3.supabase_storage import resolve_media_url
    from app.core.config import settings
    from unittest.mock import patch

    # Mock settings.BACKEND_BASE_URL
    with patch.object(settings, "BACKEND_BASE_URL", "https://backend.cobrother.com"):
        url = "http://127.0.0.1:8000/uploads/community-images/linkedin_abc.jpg"
        resolved = resolve_media_url(url)
        assert resolved == "https://backend.cobrother.com/uploads/community-images/linkedin_abc.jpg"


def test_usable_creator_media_url_keeps_prod_uploads_and_hides_dead_cdn():
    from app.service.community.community_service import CommunityService
    from app.core.config import settings
    from unittest.mock import patch

    licdn = (
        "https://media.licdn.com/dms/image/v2/D5603AQH/profile-displayphoto-scale_200_200/"
        "0/1779867477861?e=1785369600&v=beta&t=abc"
    )
    assert CommunityService._usable_creator_media_url(licdn) is None

    with patch.object(settings, "BACKEND_BASE_URL", "http://127.0.0.1:8000"):
        # Missing local file after rewrite — keep the original prod host URL.
        prod = "https://backend.cobrother.com/uploads/community-images/linkedin_N006iJzh81.jpg"
        assert CommunityService._usable_creator_media_url(prod) == prod

        # CDN with a linkedin_id falls back to durable uploads path on prod.
        restored = CommunityService._usable_creator_media_url(
            licdn,
            linkedin_id="p_zvc2YQ4x",
        )
        assert restored == (
            "https://backend.cobrother.com/uploads/community-images/linkedin_p_zvc2YQ4x.jpg"
        )
