"""Virtual Assistant role string normalization (no DB whitelist)."""

from fastapi import HTTPException, status

VA_ROLE_OTHER_SENTINEL = "Other (Specify Your Role)"
VA_ROLE_MAX_LEN = 100


def normalize_va_role_name(role: str | None) -> str:
    """
    Trim and validate a single VA role name for create/submit paths.

    Allows any profession string (including custom roles). Rejects empty values,
    the UI "Other" sentinel, commas (roles are comma-split on intake), and
    lengths above ApplicationRole.role_name (100).
    """
    role_name = (role or "").strip()
    if not role_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Exactly one Virtual Assistant role is required per application.",
        )
    if role_name == VA_ROLE_OTHER_SENTINEL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide a specific role name instead of Other.",
        )
    if "," in role_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role cannot contain commas.",
        )
    if len(role_name) > VA_ROLE_MAX_LEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role must be {VA_ROLE_MAX_LEN} characters or fewer.",
        )
    return role_name
