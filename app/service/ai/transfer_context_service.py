"""Live domain transfer context for HubRegistrar AI assistant."""

from __future__ import annotations

import re
import uuid
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.entity.domain.domain_marketplace_transaction_entity import DomainMarketplaceTransaction
from app.entity.user.app_user import AppUser
from app.model.marketplace.transfer_mapper import build_transfer_response
from app.repository.domain_marketplace_transaction_repository import (
    DomainMarketplaceTransactionRepository,
)
from app.repository.seller_payout_profile_repository import SellerPayoutProfileRepository
from app.service.auth.transfer_auth_reveal_otp_service import TransferAuthRevealOtpService
from app.service.payout.seller_payout_profile_service import SellerPayoutProfileService
from app.utils.transfer_enums import MarketplaceTransferStatus

_ROUTE_TX_PATTERN = re.compile(
    r"(?:/purchases/transfers/|/domains/transfers/)([0-9a-f-]{36})",
    re.IGNORECASE,
)
_DOMAIN_PATTERN = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}\b",
    re.IGNORECASE,
)

_TERMINAL_STATUSES = frozenset(
    {
        MarketplaceTransferStatus.COMPLETED,
        MarketplaceTransferStatus.SELLER_PAID,
        MarketplaceTransferStatus.PAYOUT_RELEASED,
        MarketplaceTransferStatus.REFUNDED,
        MarketplaceTransferStatus.CANCELLED,
    },
)


class TransferContextService:
    """Resolve the user's active transfer and expose safe workflow context for Bro AI."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DomainMarketplaceTransactionRepository(session)
        self._payout_profiles = SellerPayoutProfileRepository(session)
        self._otp = TransferAuthRevealOtpService()

    async def build_for_user(
        self,
        user: AppUser | None,
        *,
        message: str = "",
        page_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        page_context = page_context or {}
        if user is None:
            return {"available": False, "reason": "not_authenticated"}

        tx = await self._resolve_transaction(user, message=message, page_context=page_context)
        if tx is None:
            return {"available": False, "reason": "no_transfer_found"}

        role = self._user_role(user, tx)
        summary = build_transfer_response(tx)
        otp_status = await self._otp_status(tx, user, role)
        auth_code_status = self._auth_code_status(tx, role)
        payout_status = await self._payout_status(tx, user, role)
        escrow_status = self._escrow_status(tx)

        context: dict[str, Any] = {
            "available": True,
            "transaction_id": str(tx.id),
            "domain_fqdn": tx.domain_fqdn,
            "user_role": role,
            "current_route": page_context.get("current_route"),
            "transfer_status": tx.transfer_status.value,
            "escrow_status": escrow_status,
            "transfer_method": tx.transfer_method.value if tx.transfer_method else None,
            "seller_registrar_name": tx.seller_registrar_name,
            "buyer_target_registrar": tx.buyer_target_registrar,
            "dispute_status": tx.dispute_status.value,
            "order": {
                "id": str(tx.id),
                "domain": tx.domain_fqdn,
                "gross_amount_inr": tx.gross_amount_inr,
                "seller_payout_inr": tx.seller_payout_inr,
                "platform_fee_inr": tx.platform_fee_inr,
            },
            "transfer": summary,
            "auth_code_status": auth_code_status,
            "otp_status": otp_status,
            "escrow": escrow_status,
            "payout_status": payout_status,
            "next_step": self._next_step(tx, role, auth_code_status, otp_status, payout_status),
        }
        return context

    async def get_current_order(
        self,
        user: AppUser,
        *,
        page_context: dict[str, Any] | None = None,
        message: str = "",
    ) -> dict[str, Any] | None:
        ctx = await self.build_for_user(user, message=message, page_context=page_context)
        return ctx.get("order") if ctx.get("available") else None

    async def get_transfer_status(
        self,
        user: AppUser,
        *,
        page_context: dict[str, Any] | None = None,
        message: str = "",
    ) -> dict[str, Any] | None:
        ctx = await self.build_for_user(user, message=message, page_context=page_context)
        if not ctx.get("available"):
            return None
        return {
            "transfer_status": ctx["transfer_status"],
            "transfer_method": ctx.get("transfer_method"),
            "domain": ctx.get("domain_fqdn"),
            "user_role": ctx.get("user_role"),
            "next_step": ctx.get("next_step"),
        }

    async def get_auth_code_status(
        self,
        user: AppUser,
        *,
        page_context: dict[str, Any] | None = None,
        message: str = "",
    ) -> dict[str, Any] | None:
        ctx = await self.build_for_user(user, message=message, page_context=page_context)
        return ctx.get("auth_code_status") if ctx.get("available") else None

    async def get_otp_status(
        self,
        user: AppUser,
        *,
        page_context: dict[str, Any] | None = None,
        message: str = "",
    ) -> dict[str, Any] | None:
        ctx = await self.build_for_user(user, message=message, page_context=page_context)
        return ctx.get("otp_status") if ctx.get("available") else None

    async def get_escrow_status(
        self,
        user: AppUser,
        *,
        page_context: dict[str, Any] | None = None,
        message: str = "",
    ) -> dict[str, Any] | None:
        ctx = await self.build_for_user(user, message=message, page_context=page_context)
        return ctx.get("escrow") if ctx.get("available") else None

    async def get_payout_status(
        self,
        user: AppUser,
        *,
        page_context: dict[str, Any] | None = None,
        message: str = "",
    ) -> dict[str, Any] | None:
        ctx = await self.build_for_user(user, message=message, page_context=page_context)
        return ctx.get("payout_status") if ctx.get("available") else None

    async def _resolve_transaction(
        self,
        user: AppUser,
        *,
        message: str,
        page_context: dict[str, Any],
    ) -> DomainMarketplaceTransaction | None:
        tx_id = self._parse_uuid(page_context.get("transaction_id"))
        if tx_id is None:
            tx_id = self._parse_transaction_id_from_route(page_context.get("current_route"))

        if tx_id is not None:
            tx = await self._repo.get_by_id(tx_id)
            if tx and self._user_can_access(user, tx):
                return tx
            return None

        domain = (page_context.get("domain_fqdn") or self._extract_domain(message) or "").strip().lower()
        if domain:
            for tx in await self._list_user_transfers(user, page_context):
                if (tx.domain_fqdn or "").lower() == domain:
                    return tx

        transfers = await self._list_user_transfers(user, page_context)
        for tx in transfers:
            if tx.transfer_status not in _TERMINAL_STATUSES:
                return tx
        return transfers[0] if transfers else None

    async def _list_user_transfers(
        self,
        user: AppUser,
        page_context: dict[str, Any],
    ) -> list[DomainMarketplaceTransaction]:
        route = (page_context.get("current_route") or "").lower()
        prefer_seller = "/domains/transfers/" in route
        prefer_buyer = "/purchases/transfers/" in route

        seller_rows = list(await self._repo.list_by_seller(user.id))
        buyer_rows = list(await self._repo.list_by_buyer(user.id))

        if prefer_seller and seller_rows:
            return seller_rows
        if prefer_buyer and buyer_rows:
            return buyer_rows
        return buyer_rows or seller_rows

    @staticmethod
    def _parse_uuid(value: Any) -> uuid.UUID | None:
        if value is None:
            return None
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError, AttributeError):
            return None

    @staticmethod
    def _parse_transaction_id_from_route(route: str | None) -> uuid.UUID | None:
        if not route:
            return None
        match = _ROUTE_TX_PATTERN.search(route)
        if not match:
            return None
        return TransferContextService._parse_uuid(match.group(1))

    @staticmethod
    def _extract_domain(message: str) -> str | None:
        match = _DOMAIN_PATTERN.search(message or "")
        if not match:
            return None
        return match.group(0).strip(".,;:!?()[]{}\"'")

    @staticmethod
    def _user_can_access(user: AppUser, tx: DomainMarketplaceTransaction) -> bool:
        return user.id in {tx.buyer_id, tx.seller_id}

    @staticmethod
    def _user_role(user: AppUser, tx: DomainMarketplaceTransaction) -> Literal["buyer", "seller"]:
        if tx.buyer_id == user.id:
            return "buyer"
        return "seller"

    async def _otp_status(
        self,
        tx: DomainMarketplaceTransaction,
        user: AppUser,
        role: str,
    ) -> dict[str, Any]:
        if role != "buyer" or not tx.auth_code_ciphertext:
            return {
                "required_for_reveal": False,
                "verified": False,
                "pending": False,
                "sent": False,
            }

        verified = tx.auth_code_viewed_at is not None
        pending = False if verified else await self._otp.has_pending_otp(tx.id, user.id)
        return {
            "required_for_reveal": True,
            "verified": verified,
            "pending": pending,
            "sent": pending or verified,
        }

    @staticmethod
    def _auth_code_status(tx: DomainMarketplaceTransaction, role: str) -> dict[str, Any]:
        has_code = bool(tx.auth_code_ciphertext)
        submitted = tx.auth_code_submitted_at is not None
        viewed = tx.auth_code_viewed_at is not None
        if not has_code:
            status = "not_submitted"
        elif viewed:
            status = "viewed"
        elif submitted or tx.transfer_status in (
            MarketplaceTransferStatus.AUTH_CODE_AVAILABLE,
            MarketplaceTransferStatus.AUTH_CODE_RECEIVED,
            MarketplaceTransferStatus.AUTH_CODE_VIEWED,
        ):
            status = "available"
        else:
            status = "pending"

        return {
            "has_code": has_code,
            "submitted": submitted,
            "viewed": viewed,
            "status": status,
            "submitted_at": tx.auth_code_submitted_at.isoformat() if tx.auth_code_submitted_at else None,
            "viewed_at": tx.auth_code_viewed_at.isoformat() if tx.auth_code_viewed_at else None,
            "visible_to_buyer_after_otp": has_code and role == "buyer",
        }

    @staticmethod
    def _escrow_status(tx: DomainMarketplaceTransaction) -> dict[str, Any]:
        return {
            "status": tx.escrow_status.value,
            "held": tx.escrow_status.value == "HELD",
            "released": tx.escrow_status.value == "RELEASED",
            "refunded": tx.escrow_status.value == "REFUNDED",
        }

    async def _payout_status(
        self,
        tx: DomainMarketplaceTransaction,
        user: AppUser,
        role: str,
    ) -> dict[str, Any]:
        profile = await self._payout_profiles.get_by_user_id(tx.seller_id)
        profile_complete = SellerPayoutProfileService.is_complete(profile)
        eligible = tx.transfer_status in (
            MarketplaceTransferStatus.PAYOUT_PENDING,
            MarketplaceTransferStatus.PAYOUT_APPROVED,
            MarketplaceTransferStatus.PAYOUT_RELEASED,
            MarketplaceTransferStatus.SELLER_PAID,
            MarketplaceTransferStatus.COMPLETED,
            MarketplaceTransferStatus.TRANSFER_COMPLETED,
        )
        return {
            "status": tx.transfer_status.value,
            "eligible": eligible,
            "seller_payout_inr": tx.seller_payout_inr if role == "seller" else None,
            "payout_profile_complete": profile_complete if role == "seller" else None,
            "payout_approved_at": tx.payout_approved_at.isoformat() if tx.payout_approved_at else None,
            "seller_paid_at": tx.seller_paid_at.isoformat() if tx.seller_paid_at else None,
        }

    @staticmethod
    def _next_step(
        tx: DomainMarketplaceTransaction,
        role: str,
        auth_code_status: dict[str, Any],
        otp_status: dict[str, Any],
        payout_status: dict[str, Any],
    ) -> str:
        status = tx.transfer_status

        if role == "seller":
            if status == MarketplaceTransferStatus.PAYMENT_COMPLETED:
                return "Submit the authorization code and transfer details on your seller transfer page."
            if status == MarketplaceTransferStatus.AWAITING_AUTH_CODE:
                return "Unlock the domain at your registrar, obtain the auth code, and submit it in HubRegistrar."
            if status in (
                MarketplaceTransferStatus.AUTH_CODE_AVAILABLE,
                MarketplaceTransferStatus.AUTH_CODE_RECEIVED,
                MarketplaceTransferStatus.AUTH_CODE_VIEWED,
                MarketplaceTransferStatus.TRANSFER_IN_PROGRESS,
            ):
                return "Wait for the buyer to initiate and confirm the transfer at their registrar."
            if status == MarketplaceTransferStatus.PAYOUT_PENDING:
                if not payout_status.get("payout_profile_complete"):
                    return "Complete Payout Settings (bank or UPI), then wait for admin payout release."
                return "Your payout is eligible. Admin will review and release funds manually."
            if status in (
                MarketplaceTransferStatus.PAYOUT_APPROVED,
                MarketplaceTransferStatus.PAYOUT_RELEASED,
                MarketplaceTransferStatus.SELLER_PAID,
                MarketplaceTransferStatus.COMPLETED,
            ):
                return "Payout has been processed or is complete."
            if status == MarketplaceTransferStatus.REFUNDED:
                return "This transaction was refunded."

        if status == MarketplaceTransferStatus.PAYMENT_COMPLETED:
            return "The seller is preparing transfer information. You will be notified when the auth code is available."
        if status == MarketplaceTransferStatus.AWAITING_AUTH_CODE:
            return "Payment is complete. Wait for the seller to submit the authorization code."
        if status in (
            MarketplaceTransferStatus.AUTH_CODE_AVAILABLE,
            MarketplaceTransferStatus.AUTH_CODE_RECEIVED,
        ):
            if otp_status.get("required_for_reveal") and not otp_status.get("verified"):
                return "Verify the OTP sent to your email to reveal the authorization code."
            return "Your authorization code is ready. Begin the transfer at your registrar."
        if status == MarketplaceTransferStatus.AUTH_CODE_VIEWED:
            return "Initiate the domain transfer at your registrar, then mark transfer as started in HubRegistrar."
        if status == MarketplaceTransferStatus.TRANSFER_IN_PROGRESS:
            return "Wait for your registrar to complete the transfer, then confirm completion in HubRegistrar."
        if status in (
            MarketplaceTransferStatus.TRANSFER_COMPLETED,
            MarketplaceTransferStatus.PAYOUT_PENDING,
            MarketplaceTransferStatus.PAYOUT_APPROVED,
            MarketplaceTransferStatus.PAYOUT_RELEASED,
            MarketplaceTransferStatus.SELLER_PAID,
            MarketplaceTransferStatus.COMPLETED,
        ):
            return "Your transfer has been completed successfully."
        if status == MarketplaceTransferStatus.REFUNDED:
            return "This order was refunded."
        if status == MarketplaceTransferStatus.DISPUTED:
            return "This transfer is under dispute review. HubRegistrar support will follow up."
        if auth_code_status.get("status") == "not_submitted":
            return "Wait for the seller to submit the authorization code."
        return "Review your transfer page for the latest status and available actions."
