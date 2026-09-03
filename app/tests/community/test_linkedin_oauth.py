from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.service.community import linkedin_oauth


def test_resolve_linkedin_redirect_uri_from_production_backend_host():
    uri = linkedin_oauth.resolve_linkedin_redirect_uri(
        request_host="backend.cobrother.com",
        request_scheme="https",
    )
    assert uri == "https://backend.cobrother.com/api/v1/community/linkedin/callback"


def test_resolve_linkedin_redirect_uri_from_legacy_cobrother_subdomain():
    uri = linkedin_oauth.resolve_linkedin_redirect_uri(
        request_host="demo.cobrother.com",
        request_scheme="https",
    )
    assert uri == "https://demo.cobrother.com/api/v1/community/linkedin/callback"


def test_resolve_linkedin_redirect_uri_from_localhost():
    uri = linkedin_oauth.resolve_linkedin_redirect_uri(
        request_host="127.0.0.1:8000",
        request_scheme="http",
    )
    assert uri == "http://127.0.0.1:8000/api/v1/community/linkedin/callback"


def test_resolve_linkedin_redirect_uri_falls_back_to_env():
    with patch.object(
        settings,
        "LINKEDIN_REDIRECT_URI",
        "https://backend.cobrother.com/api/v1/community/linkedin/callback",
    ):
        uri = linkedin_oauth.resolve_linkedin_redirect_uri(
            request_host="unknown.example.com",
            request_scheme="https",
        )
    assert uri == "https://backend.cobrother.com/api/v1/community/linkedin/callback"


def test_resolve_linkedin_redirect_uri_falls_back_to_backend_base_url():
    with patch.object(settings, "LINKEDIN_REDIRECT_URI", ""), patch.object(
        settings,
        "BACKEND_BASE_URL",
        "https://backend.cobrother.com",
    ):
        uri = linkedin_oauth.resolve_linkedin_redirect_uri()
    assert uri == "https://backend.cobrother.com/api/v1/community/linkedin/callback"


def test_normalize_profile_url_adds_trailing_slash():
    assert (
        linkedin_oauth.normalize_profile_url("https://www.linkedin.com/in/jane")
        == "https://www.linkedin.com/in/jane/"
    )


def test_extract_profile_url_from_identity_me_profile_url():
    url, strategy = linkedin_oauth.extract_profile_url_from_identity_me(
        {
            "basicInfo": {
                "profileUrl": "https://www.linkedin.com/in/jane-doe",
            }
        }
    )
    assert url == "https://www.linkedin.com/in/jane-doe/"
    assert strategy == "identityMe_basicInfo_profileUrl"


def test_extract_profile_url_from_identity_me_vanity_name():
    url, strategy = linkedin_oauth.extract_profile_url_from_identity_me(
        {
            "basicInfo": {
                "vanityName": "jane-identity",
            }
        }
    )
    assert url == "https://www.linkedin.com/in/jane-identity/"
    assert strategy == "identityMe_basicInfo_vanityName"


def _mock_identity_me_response(*, status_code: int, text: str, json_body: dict | None):
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    if json_body is not None:
        response.json.return_value = json_body
    return response


def test_fetch_linkedin_member_profile_calls_identity_me_with_version_header():
    identity_response = _mock_identity_me_response(
        status_code=200,
        text='{"basicInfo":{"profileUrl":"https://www.linkedin.com/in/jane"}}',
        json_body={"basicInfo": {"profileUrl": "https://www.linkedin.com/in/jane"}},
    )

    with patch.object(
        linkedin_oauth,
        "fetch_openid_userinfo",
        return_value={"sub": "abc123", "name": "Jane Doe"},
    ), patch("app.service.community.linkedin_oauth.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = identity_response
        linkedin_oauth.fetch_linkedin_member_profile("token")

    client_cls.return_value.__enter__.return_value.get.assert_called_once_with(
        linkedin_oauth.LINKEDIN_IDENTITY_ME_URL,
        headers={
            "Authorization": "Bearer token",
            "LinkedIn-Version": "202510.03",
        },
    )


def test_fetch_linkedin_member_profile_uses_identity_me_profile_url():
    identity_response = _mock_identity_me_response(
        status_code=200,
        text='{"basicInfo":{"profileUrl":"https://www.linkedin.com/in/jane-doe"}}',
        json_body={"basicInfo": {"profileUrl": "https://www.linkedin.com/in/jane-doe"}},
    )

    with patch.object(
        linkedin_oauth,
        "fetch_openid_userinfo",
        return_value={
            "sub": "abc123",
            "name": "Jane Doe",
            "email": "jane@example.com",
            "picture": "https://cdn.example/avatar.jpg",
        },
    ), patch("app.service.community.linkedin_oauth.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = identity_response
        profile = linkedin_oauth.fetch_linkedin_member_profile("token")

    assert profile["profile_url"] == "https://www.linkedin.com/in/jane-doe/"
    assert profile["linked_in_id"] == "abc123"


def test_fetch_linkedin_member_profile_uses_identity_me_vanity_name():
    identity_response = _mock_identity_me_response(
        status_code=200,
        text='{"basicInfo":{"vanityName":"jane-doe"}}',
        json_body={"basicInfo": {"vanityName": "jane-doe"}},
    )

    with patch.object(
        linkedin_oauth,
        "fetch_openid_userinfo",
        return_value={
            "sub": "abc123",
            "name": "Jane Doe",
            "email": "jane@example.com",
            "picture": "https://cdn.example/avatar.jpg",
        },
    ), patch("app.service.community.linkedin_oauth.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = identity_response
        profile = linkedin_oauth.fetch_linkedin_member_profile("token")

    assert profile["profile_url"] == "https://www.linkedin.com/in/jane-doe/"


def test_fetch_linkedin_member_profile_allows_missing_profile_url():
    identity_response = _mock_identity_me_response(
        status_code=200,
        text='{"basicInfo":{}}',
        json_body={"basicInfo": {}},
    )

    with patch.object(
        linkedin_oauth,
        "fetch_openid_userinfo",
        return_value={"sub": "abc123", "name": "Jane Doe"},
    ), patch("app.service.community.linkedin_oauth.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = identity_response
        profile = linkedin_oauth.fetch_linkedin_member_profile("token")

    assert profile["linked_in_id"] == "abc123"
    assert profile["profile_url"] is None
