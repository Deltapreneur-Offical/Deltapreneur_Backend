from app.core.oauth_state import (
    create_oauth_state,
    parse_oauth_state,
    verify_oauth_state,
)


def test_oauth_state_round_trip():
    state = create_oauth_state("google")
    assert verify_oauth_state(state, provider="google")


def test_oauth_state_rejects_tampered_signature():
    state = create_oauth_state("google")
    payload, _sig = state.rsplit(".", 1)
    tampered = f"{payload}.deadbeef"
    assert not verify_oauth_state(tampered, provider="google")


def test_oauth_state_rejects_wrong_provider():
    state = create_oauth_state("google")
    assert not verify_oauth_state(state, provider="other")


def test_oauth_state_keeps_return_origin_extra():
    state = create_oauth_state("google", return_origin="https://cobrother.com")
    payload = parse_oauth_state(state, provider="google")
    assert payload is not None
    assert payload["return_origin"] == "https://cobrother.com"


def test_oauth_state_round_trip():
    state = create_oauth_state("google")
    assert verify_oauth_state(state, provider="google")


def test_oauth_state_rejects_tampered_signature():
    state = create_oauth_state("google")
    payload, _sig = state.rsplit(".", 1)
    tampered = f"{payload}.deadbeef"
    assert not verify_oauth_state(tampered, provider="google")


def test_oauth_state_rejects_wrong_provider():
    state = create_oauth_state("google")
    assert not verify_oauth_state(state, provider="other")
