"""WHOIS/RDAP supporting evidence for in-progress transfers."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.entity.domain.domain_marketplace_transaction_entity import DomainMarketplaceTransaction
from app.repository.domain_marketplace_transaction_repository import (
    DomainMarketplaceTransactionRepository,
)
from app.service.domain.domain_transfer_event_service import DomainTransferEventService
from app.service.domain.domain_transfer_instruction_service import normalize_registrar_key
from app.utils.transfer_enums import MarketplaceTransferStatus, TransferEventType

logger = logging.getLogger(__name__)


def _normalize_registrar_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


async def lookup_registrar_name(fqdn: str) -> str | None:
    """Return registrar org name from RDAP, if available."""
    fqdn = fqdn.strip().lower()
    url = f"https://rdap.org/domain/{fqdn}"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url, headers={"Accept": "application/rdap+json"})
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("RDAP registrar lookup failed for %s: %s", fqdn, exc)
        return None

    for entity in data.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        roles = [str(r).lower() for r in (entity.get("roles") or [])]
        if "registrar" not in roles:
            continue
        vcard = entity.get("vcardArray")
        if isinstance(vcard, list) and len(vcard) > 1:
            for item in vcard[1]:
                if isinstance(item, list) and len(item) >= 4 and str(item[0]).lower() == "fn":
                    return str(item[3]).strip() or None
    return None


class DomainTransferWhoisService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DomainMarketplaceTransactionRepository(session)
        self._events = DomainTransferEventService(session)

    async def sync_transaction(self, tx_id: uuid.UUID) -> dict:
        tx = await self._repo.get_by_id(tx_id)
        if tx is None:
            return {"supportsTransfer": None}
        return await self._check_tx(tx, force=True)

    async def _check_tx(self, tx: DomainMarketplaceTransaction, *, force: bool = False) -> dict:
        now = datetime.now(timezone.utc)
        poll_hours = settings.DOMAIN_TRANSFER_WHOIS_POLL_HOURS
        if (
            not force
            and tx.whois_last_checked_at
            and tx.whois_last_checked_at > now - timedelta(hours=poll_hours)
        ):
            return {
                "supportsTransfer": tx.whois_supports_transfer,
                "registrar": tx.whois_registrar_snapshot,
            }

        registrar = await lookup_registrar_name(tx.domain_fqdn)
        tx.whois_last_checked_at = now
        tx.whois_registrar_snapshot = registrar
        supports = None
        if registrar and tx.buyer_target_registrar:
            target_key = normalize_registrar_key(tx.buyer_target_registrar)
            snap_key = normalize_registrar_key(registrar)
            supports = target_key in snap_key or snap_key in target_key or (
                _normalize_registrar_name(registrar)
                == _normalize_registrar_name(tx.buyer_target_registrar)
            )
        tx.whois_supports_transfer = supports
        await self._repo.save(tx)
        await self._events.log(
            tx.id,
            TransferEventType.WHOIS_CHECK,
            actor_role="SYSTEM",
            payload={"registrar": registrar, "supportsTransfer": supports},
        )
        return {"supportsTransfer": supports, "registrar": registrar}

    async def poll_in_progress(self, *, limit: int = 50) -> int:
        now = datetime.now(timezone.utc)
        poll_hours = settings.DOMAIN_TRANSFER_WHOIS_POLL_HOURS
        cutoff = now - timedelta(hours=poll_hours)
        stmt = (
            select(DomainMarketplaceTransaction)
            .where(
                DomainMarketplaceTransaction.transfer_status.in_(
                    (
                        MarketplaceTransferStatus.TRANSFER_IN_PROGRESS,
                        MarketplaceTransferStatus.AUTH_CODE_VIEWED,
                    ),
                ),
            )
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        count = 0
        for tx in rows:
            if tx.whois_last_checked_at and tx.whois_last_checked_at > cutoff:
                continue
            await self._check_tx(tx)
            count += 1
        return count
