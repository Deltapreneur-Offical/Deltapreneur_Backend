"""Unit tests for VA role normalization (no database)."""

import pytest
from fastapi import HTTPException

from app.utils.virtual_assistant_roles import (
    VA_ROLE_MAX_LEN,
    VA_ROLE_OTHER_SENTINEL,
    normalize_va_role_name,
)


def test_normalize_accepts_custom_role():
    assert normalize_va_role_name("  Blockchain Developer  ") == "Blockchain Developer"


def test_normalize_rejects_empty():
    with pytest.raises(HTTPException) as exc:
        normalize_va_role_name("   ")
    assert exc.value.status_code == 400


def test_normalize_rejects_other_sentinel():
    with pytest.raises(HTTPException) as exc:
        normalize_va_role_name(VA_ROLE_OTHER_SENTINEL)
    assert "Other" in exc.value.detail


def test_normalize_rejects_comma():
    with pytest.raises(HTTPException) as exc:
        normalize_va_role_name("A, B")
    assert "comma" in exc.value.detail.lower()


def test_normalize_rejects_too_long():
    with pytest.raises(HTTPException) as exc:
        normalize_va_role_name("x" * (VA_ROLE_MAX_LEN + 1))
    assert str(VA_ROLE_MAX_LEN) in exc.value.detail
