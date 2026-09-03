"""Fernet encryption for EPP/auth codes and payout account details."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    raw = (settings.AUTH_CODE_ENCRYPTION_KEY or "").strip()
    if not raw:
        # Dev fallback derived from JWT secret — set AUTH_CODE_ENCRYPTION_KEY in production.
        digest = hashlib.sha256(settings.JWT_SECRET_KEY.encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    else:
        key = raw.encode() if isinstance(raw, str) else raw
    return Fernet(key)


def encrypt_secret(plaintext: str, *, version: int = 1) -> str:
    token = _fernet().encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_secret(ciphertext: str, *, version: int = 1) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Could not decrypt secret.") from exc


def mask_account(value: str, *, visible: int = 4) -> str:
    if len(value) <= visible:
        return "*" * len(value)
    return "*" * (len(value) - visible) + value[-visible:]
