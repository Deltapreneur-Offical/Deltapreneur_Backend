from app.service.admin.homepage_feature_limit import (
    HOMEPAGE_FEATURE_MAX,
    HOMEPAGE_FEATURE_MAX_MESSAGE,
    homepage_feature_limit_payload,
    is_homepage_feature_limit_error,
    should_block_homepage_feature,
)


def test_allows_featuring_when_count_is_under_max():
    assert should_block_homepage_feature(0, currently_featured=False, want_featured=True) is False
    assert should_block_homepage_feature(7, currently_featured=False, want_featured=True) is False


def test_blocks_a_ninth_feature_in_the_same_section():
    assert should_block_homepage_feature(HOMEPAGE_FEATURE_MAX, currently_featured=False, want_featured=True) is True


def test_allows_unfeature_and_already_featured_noop():
    assert should_block_homepage_feature(8, currently_featured=True, want_featured=False) is False
    assert should_block_homepage_feature(8, currently_featured=True, want_featured=True) is False


def test_limit_error_payload_matches_admin_warning():
    payload = homepage_feature_limit_payload()
    assert payload["success"] is False
    assert payload["featured"] is False
    assert payload["error"] == HOMEPAGE_FEATURE_MAX_MESSAGE
    assert is_homepage_feature_limit_error(payload) is True
    assert is_homepage_feature_limit_error({"success": False, "error": "Entity not found"}) is False
