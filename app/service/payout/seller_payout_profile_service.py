"""Seller payout profile CRUD."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import re
from typing import Any

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.entity.payout.seller_payout_profile_audit_entity import SellerPayoutProfileAuditEvent
from app.entity.payout.seller_payout_profile_entity import SellerPayoutProfile
from app.entity.user.app_user import AppUser
from app.integrations.s3.upload_service import upload_image
from app.repository.seller_payout_profile_repository import SellerPayoutProfileRepository
from app.service.security.auth_code_encryption_service import decrypt_secret, encrypt_secret, mask_account
from app.utils.transfer_enums import PayoutMethod, SellerKycStatus

UPI_RE = re.compile(r"^[A-Za-z0-9._-]{2,256}@[A-Za-z]{2,64}$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
MASKED_VALUE_RE = re.compile(r"^[*Xx]+[0-9A-Za-z]{0,6}$")


def _parse_payout_method(value: str) -> PayoutMethod:
    normalized = (value or "").strip().upper().replace("-", "_")
    try:
        return PayoutMethod(normalized)
    except ValueError as exc:
        raise AppException("Invalid payout method.", status_code=400) from exc

class SellerPayoutProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SellerPayoutProfileRepository(session)

    @staticmethod
    def _decrypt_legacy_account_number(profile: SellerPayoutProfile | None) -> str:
        if profile is None or not profile.bank_account_number_encrypted:
            return ""
        try:
            return decrypt_secret(profile.bank_account_number_encrypted).strip()
        except ValueError:
            return ""

    @staticmethod
    def is_complete(profile: SellerPayoutProfile | None) -> bool:
        if profile is None:
            return False
        account_number = (profile.account_number or "").strip()
        if profile.payout_method == PayoutMethod.UPI:
            return bool(profile.upi_id_encrypted)
        if profile.payout_method == PayoutMethod.BANK_ACCOUNT:
            return bool(
                (profile.account_holder_name or "").strip()
                and (profile.bank_name or "").strip()
                and account_number
                and (profile.bank_ifsc or "").strip()
            )
        return False

    @staticmethod
    def _masked_account_number(account_number: str | None, last4: str | None = None) -> str | None:
        value = (account_number or "").strip()
        suffix = (last4 or "").strip()
        if value:
            return mask_account(value)
        if suffix:
            return f"XXXXXXXXXX{suffix}"
        return None

    def _serialize(self, profile: SellerPayoutProfile) -> dict[str, Any]:
        masked_bank = self._masked_account_number(
            profile.account_number,
            profile.account_number_last4,
        )
        masked_upi = None
        if not masked_bank and profile.bank_account_number_encrypted:
            try:
                plain = decrypt_secret(profile.bank_account_number_encrypted)
                masked_bank = mask_account(plain)
            except ValueError:
                masked_bank = "****"
        if profile.upi_id_encrypted:
            try:
                plain = decrypt_secret(profile.upi_id_encrypted)
                masked_upi = mask_account(plain, visible=3)
            except ValueError:
                masked_upi = "****"
        is_complete = self.is_complete(profile)
        has_account_number = bool((profile.account_number or "").strip())
        return {
            "id": str(profile.id),
            "payoutMethod": profile.payout_method.value,
            "accountHolderName": profile.account_holder_name,
            "bankName": profile.bank_name,
            "bankIfsc": profile.bank_ifsc,
            "masked_account_number": masked_bank,
            "maskedAccountNumber": masked_bank,
            "maskedBankAccount": masked_bank,
            "has_account_number": has_account_number,
            "hasAccountNumber": has_account_number,
            "maskedUpiId": masked_upi,
            "isComplete": is_complete,
            "kycStatus": profile.kyc_status.value,
            "beneficiaryValidatedAt": (
                profile.beneficiary_validated_at.isoformat()
                if profile.beneficiary_validated_at
                else None
            ),
            "createdAt": profile.created_at.isoformat() if profile.created_at else None,
            "updatedAt": profile.updated_at.isoformat() if profile.updated_at else None,
        }

    async def get_my_profile(self, user: AppUser) -> dict[str, Any] | None:
        profile = await self._repo.get_by_user_id(user.id)
        if profile is None:
            return None
        return self._serialize(profile)

    async def upsert_profile(
        self,
        user: AppUser,
        *,
        payout_method: str,
        account_holder_name: str | None = None,
        bank_name: str | None = None,
        bank_account_number: str | None = None,
        confirm_bank_account_number: str | None = None,
        bank_ifsc: str | None = None,
        upi_id: str | None = None,
        kyc_file: UploadFile | None = None,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        method = _parse_payout_method(payout_method)
        profile = await self._repo.get_by_user_id(user.id)
        existing_account_number = ""
        if profile is not None:
            existing_account_number = (
                (profile.account_number or "").strip()
                or self._decrypt_legacy_account_number(profile)
            )
        has_existing_account_number = bool(existing_account_number)
        incoming_account_number = (bank_account_number or "").strip()
        incoming_confirm_account_number = (confirm_bank_account_number or "").strip()

        if method == PayoutMethod.BANK_ACCOUNT:
            if not (account_holder_name and account_holder_name.strip()):
                raise AppException("Account holder name is required.", status_code=400)
            if not (bank_name and bank_name.strip()):
                raise AppException("Bank name is required.", status_code=400)
            if not incoming_account_number and not has_existing_account_number:
                raise AppException("Account number is required.", status_code=400)
            if incoming_account_number and MASKED_VALUE_RE.fullmatch(incoming_account_number):
                raise AppException("Enter the full account number, not a masked value.", status_code=400)
            if incoming_account_number:
                if not incoming_confirm_account_number:
                    raise AppException("Confirm account number is required.", status_code=400)
                if incoming_account_number != incoming_confirm_account_number:
                    raise AppException("Account numbers do not match.", status_code=400)
            if not (bank_ifsc and bank_ifsc.strip()):
                raise AppException("IFSC code is required.", status_code=400)
            if not IFSC_RE.fullmatch(bank_ifsc.strip().upper()):
                raise AppException("Enter a valid IFSC code.", status_code=400)
        elif method == PayoutMethod.UPI:
            if not (upi_id and upi_id.strip()):
                raise AppException("UPI ID is required.", status_code=400)
            if not UPI_RE.fullmatch(upi_id.strip()):
                raise AppException("Enter a valid UPI ID.", status_code=400)

        if profile is None:
            profile = SellerPayoutProfile(
                user_id=user.id,
                payout_method=method,
                account_holder_name=(account_holder_name or "").strip() or None,
                kyc_status=SellerKycStatus.SUBMITTED,
            )
        else:
            profile.payout_method = method
            profile.kyc_status = SellerKycStatus.SUBMITTED

        if method == PayoutMethod.BANK_ACCOUNT:
            profile.account_holder_name = account_holder_name.strip()
            profile.bank_name = bank_name.strip()
            if incoming_account_number:
                clean_account_number = incoming_account_number
                profile.account_number = clean_account_number
                profile.account_number_last4 = clean_account_number[-4:]
                profile.bank_account_number_encrypted = encrypt_secret(clean_account_number)
            elif existing_account_number and not profile.account_number:
                profile.account_number = existing_account_number
                profile.account_number_last4 = existing_account_number[-4:]
            profile.bank_ifsc = bank_ifsc.strip().upper()
            profile.upi_id_encrypted = None
        else:
            profile.account_holder_name = (account_holder_name or "").strip() or None
            profile.bank_name = None
            profile.account_number = None
            profile.account_number_last4 = None
            profile.upi_id_encrypted = encrypt_secret(upi_id.strip())
            profile.bank_account_number_encrypted = None
            profile.bank_ifsc = None

        profile.is_complete = self.is_complete(profile)

        if kyc_file is not None:
            url = await upload_image(file=kyc_file, folder=f"payout-kyc/{user.id}")
            profile.kyc_document_storage_key = url

        await self._repo.save(profile)
        self._session.add(
            SellerPayoutProfileAuditEvent(
                profile_id=profile.id,
                user_id=user.id,
                updated_by_user_id=user.id,
                action="PAYOUT_PROFILE_UPDATED",
                payout_method=method.value,
                ip_address=ip_address,
            )
        )
        if method == PayoutMethod.BANK_ACCOUNT and incoming_account_number:
            self._session.add(
                SellerPayoutProfileAuditEvent(
                    profile_id=profile.id,
                    user_id=user.id,
                    updated_by_user_id=user.id,
                    action="ACCOUNT_NUMBER_UPDATED",
                    payout_method=method.value,
                    ip_address=ip_address,
                )
            )
        await self._session.commit()
        return self._serialize(profile)
    async def admin_verify(self, user_id: uuid.UUID, *, admin: AppUser) -> dict[str, Any]:
        profile = await self._repo.get_by_user_id(user_id)
        if profile is None:
            raise AppException("Payout profile not found.", status_code=404)
        profile.kyc_status = SellerKycStatus.VERIFIED
        profile.beneficiary_validated_at = datetime.now(timezone.utc)
        profile.beneficiary_validation_ref = f"admin:{admin.id}"
        await self._repo.save(profile)
        await self._session.commit()
        return self._serialize(profile)
