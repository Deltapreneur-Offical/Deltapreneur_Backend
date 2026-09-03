"""Unit tests for venture/GST validation helpers."""

from app.integrations.gstin.gst_validator import normalize_gstin, validate_gstin_format


def test_validate_gstin_format_rejects_short():
    ok, err = validate_gstin_format("123")
    assert ok is False
    assert err is not None


def test_validate_gstin_format_accepts_sandbox_pattern():
    gstin = normalize_gstin("29AABCU9603R1ZM")
    ok, err = validate_gstin_format(gstin)
    assert ok is True
    assert err is None
