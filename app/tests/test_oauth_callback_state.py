"""OAuth state cookie vs signed-state validation."""

from unittest.mock import patch

from app.controller.auth.auth_controller import _oauth_state_matches
from app.core.oauth_state import create_oauth_state


def test_oauth_state_matches_when_cookie_present() -> None:
    state = create_oauth_state("google")
    assert _oauth_state_matches(state, state) is True


def test_oauth_state_dev_allows_missing_cookie() -> None:
    state = create_oauth_state("google")
    with patch(
        "app.controller.auth.auth_controller.settings"
    ) as mock_settings:
        mock_settings.ENVIRONMENT = "development"
        assert _oauth_state_matches(state, None) is True


def test_oauth_state_production_requires_cookie() -> None:
    state = create_oauth_state("google")
    with patch(
        "app.controller.auth.auth_controller.settings"
    ) as mock_settings:
        mock_settings.ENVIRONMENT = "production"
        assert _oauth_state_matches(state, None) is False
