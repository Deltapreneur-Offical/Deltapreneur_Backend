"""Venture GSTIN verification for venture listings."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.user.app_user import AppUser
from app.integrations.gstin import is_gstin_sandbox_mode, verify_gstin
from app.model.venture.venture_response import GstinVerifyResponse
from app.repository.venture_repository import VentureRepository

GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")


class VentureVerificationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = VentureRepository(session)

    async def verify_gstin_for_venture(
        self,
        venture_id: uuid.UUID,
        gstin: str,
        *,
        actor: AppUser,
    ) -> GstinVerifyResponse:
        venture = await self._repo.get_by_id(venture_id)
        if venture is None:
            raise AppException("Venture not found.", status_code=404)

        if venture.listed_by_user_id != actor.id:
            raise AppException("Not your venture.", status_code=403)

        brand_name = venture.brand_details.brand_name if venture.brand_details else None
        return await self._complete_gstin_verification(
            venture,
            venture_id,
            gstin,
            brand_name=brand_name,
            success_message="GSTIN verified successfully for your venture.",
        )

    async def verify_gstin_as_admin(
        self,
        venture_id: uuid.UUID,
        gstin: str,
    ) -> GstinVerifyResponse:
        venture = await self._repo.get_by_id(venture_id)
        if venture is None:
            raise AppException("Venture not found.", status_code=404)

        brand_name = venture.brand_details.brand_name if venture.brand_details else None
        return await self._complete_gstin_verification(
            venture,
            venture_id,
            gstin,
            brand_name=brand_name,
            success_message="GSTIN verified by admin.",
        )

    async def _complete_gstin_verification(
        self,
        venture,
        venture_id: uuid.UUID,
        gstin: str,
        *,
        brand_name: str | None,
        success_message: str,
    ) -> GstinVerifyResponse:
        normalized_gstin = gstin.strip().upper()
        if len(normalized_gstin) != 15 or not GSTIN_PATTERN.match(normalized_gstin):
            return GstinVerifyResponse(
                verified=False,
                error=(
                    "Invalid GSTIN format. Expected: 2-digit state code + PAN (10 chars) "
                    "+ entity digit + Z + check digit."
                ),
            )

        result = await verify_gstin(normalized_gstin, trade_name_hint=brand_name)
        if not result.active:
            return GstinVerifyResponse(
                verified=False,
                error=result.error_message or "GSTIN is not active.",
            )

        if (
            not is_gstin_sandbox_mode()
            and brand_name
            and result.trade_name
        ):
            if brand_name.strip().lower() != result.trade_name.strip().lower():
                return GstinVerifyResponse(
                    verified=False,
                    error=(
                        "This GSTIN does not match your venture. "
                        "Use the GSTIN registered for the same business as your listing."
                    ),
                )

        now = datetime.now(timezone.utc)
        venture.gstin = normalized_gstin
        venture.gstin_verified = True
        venture.gstin_verified_at = now
        legal_name = (result.trade_name or brand_name or "").strip()
        venture.gstin_legal_name = legal_name[:512] if legal_name else None
        venture.updated_at = now

        await self._repo.save(venture)
        await self._session.commit()

        return GstinVerifyResponse(
            verified=True,
            message=success_message,
            legal_name=legal_name,
        )
