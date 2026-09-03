"""OTP send/verify for buyer auth-code reveal."""

from __future__ import annotations

import secrets
import uuid

from app.core.config import settings
from app.core.exceptions import AppException
from app.core.security import hash_otp_code
from app.entity.user.app_user import AppUser
from app.service.auth.mail_service import MailService
from app.service.auth.transfer_auth_reveal_otp_cache import transfer_auth_reveal_otp_cache

_OTP_TTL = 600
_MAX_ATTEMPTS = 5


class TransferAuthRevealOtpService:
    def __init__(self) -> None:
        self._cache = transfer_auth_reveal_otp_cache

    def _key(self, transaction_id: uuid.UUID, buyer_id: uuid.UUID) -> str:
        return f"transfer_reveal:{transaction_id}:{buyer_id}"

    async def send_otp(self, transaction_id: uuid.UUID, buyer: AppUser) -> None:
        if not settings.mail_configured():
            raise AppException("Email is not configured.", status_code=503)
        otp = f"{secrets.randbelow(1_000_000):06d}"
        await self._cache.set_json(
            self._key(transaction_id, buyer.id),
            {"otp_hash": hash_otp_code(otp), "attempts": 0},
            _OTP_TTL,
        )
        await MailService.send_otp_login_email(buyer.email, otp)

    async def verify_otp(
        self,
        transaction_id: uuid.UUID,
        buyer: AppUser,
        otp: str,
    ) -> None:
        key = self._key(transaction_id, buyer.id)
        entry = await self._cache.get_json(key)
        if not entry:
            raise AppException("OTP expired or not sent. Request a new code.", status_code=400)
        attempts = int(entry.get("attempts", 0))
        if attempts >= _MAX_ATTEMPTS:
            raise AppException("Too many attempts. Request a new code.", status_code=429)
        expected = entry.get("otp_hash", "")
        if hash_otp_code(otp.strip()) != expected:
            entry["attempts"] = attempts + 1
            await self._cache.set_json(key, entry, _OTP_TTL)
            raise AppException("Invalid OTP.", status_code=400)
        await self._cache.delete(key)

    async def has_pending_otp(self, transaction_id: uuid.UUID, buyer_id: uuid.UUID) -> bool:
        entry = await self._cache.get_json(self._key(transaction_id, buyer_id))
        return entry is not None
