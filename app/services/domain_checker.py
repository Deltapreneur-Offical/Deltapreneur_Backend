"""Domain availability checks for AI-generated names via OpenProvider."""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.exceptions import AppException
from app.schemas.ai_domains import AIDomainAvailability
from app.service.domain.domain_registration_service import DomainRegistrationService

logger = logging.getLogger(__name__)
DEFAULT_AI_DOMAIN_TLDS: tuple[str, ...] = ("com", "in")


def _sanitize_label(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum() or ch == "-").strip("-")


def _to_ai_status(registrar_status: str) -> str:
    normalized = (registrar_status or "").strip().lower()
    if normalized == "available":
        return "available"
    if normalized == "taken":
        return "taken"
    return "unknown"


class AIDomainChecker:
    def __init__(self, registration_service: DomainRegistrationService) -> None:
        self._registration_service = registration_service
        self._semaphore = asyncio.Semaphore(20)

    async def check(self, name: str, tld: str) -> AIDomainAvailability:
        results = await self.check_many(name, (tld.lstrip("."),))
        key = tld.lstrip(".")
        return results.get(key) or AIDomainAvailability(
            domain=f"{_sanitize_label(name) or 'invalid'}.{key}",
            status="unknown",
        )

    async def check_many(
        self,
        name: str,
        tlds: tuple[str, ...] = DEFAULT_AI_DOMAIN_TLDS,
    ) -> dict[str, AIDomainAvailability]:
        safe_name = _sanitize_label(name)
        tld_list = tuple(tld.lstrip(".") for tld in tlds)
        if not safe_name:
            return {
                ext: AIDomainAvailability(domain=f"invalid.{ext}", status="unknown")
                for ext in tld_list
            }

        async with self._semaphore:
            from app.integrations import domain_registrar
            reg = domain_registrar.active_registrar()
            if hasattr(reg, "check_availability_bulk") and reg.is_configured():
                results = await self._check_many_bulk(reg, safe_name, tld_list)
            else:
                results = await self._check_many_via_service(safe_name, tld_list)

        await self._attach_prices_for_available(results)
        return results

    async def _check_many_bulk(
        self,
        reg: Any,
        safe_name: str,
        tld_list: tuple[str, ...],
    ) -> dict[str, AIDomainAvailability]:
        try:
            bulk = await reg.check_availability_bulk(safe_name, list(tld_list))
        except Exception as exc:
            logger.warning(
                "AI domain bulk check failed name=%s: %s",
                safe_name,
                exc,
            )
            return {
                ext: AIDomainAvailability(
                    domain=f"{safe_name}.{ext}",
                    available=False,
                    status="unknown",
                )
                for ext in tld_list
            }

        by_domain = {str(item.get("domain", "")).lower(): item for item in bulk}
        results: dict[str, AIDomainAvailability] = {}
        for ext in tld_list:
            fqdn = f"{safe_name}.{ext}"
            entry = by_domain.get(fqdn.lower()) or {}
            mapped = _to_ai_status(str(entry.get("status", "")))
            results[ext] = AIDomainAvailability(
                domain=fqdn,
                available=mapped == "available",
                status=mapped,  # type: ignore[arg-type]
            )
        return results

    async def _check_many_via_service(
        self,
        safe_name: str,
        tld_list: tuple[str, ...],
    ) -> dict[str, AIDomainAvailability]:
        results: dict[str, AIDomainAvailability] = {}
        for ext in tld_list:
            fqdn = f"{safe_name}.{ext}"
            results[ext] = await self._check_via_service(fqdn)
        return results

    async def _check_via_service(self, fqdn: str) -> AIDomainAvailability:
        try:
            check = await self._registration_service.check_openprovider_domain(fqdn)
        except AppException as exc:
            logger.warning("AI domain registrar check failed domain=%s: %s", fqdn, exc.message)
            return AIDomainAvailability(domain=fqdn, available=False, status="unknown")
        except Exception as exc:
            logger.warning("AI domain registrar check failed domain=%s: %s", fqdn, exc)
            return AIDomainAvailability(domain=fqdn, available=False, status="unknown")

        if check.status == "available":
            return AIDomainAvailability(
                domain=fqdn,
                available=True,
                status="available",
                price_inr=float(check.unitPrice or check.price or 0) or None,
            )
        if check.status == "taken":
            return AIDomainAvailability(
                domain=fqdn,
                available=False,
                status="taken",
            )
        return AIDomainAvailability(domain=fqdn, available=False, status="unknown")

    async def _attach_prices_for_available(
        self,
        results: dict[str, AIDomainAvailability],
    ) -> None:
        """Fetch INR unit price for available domains (same path as homepage domain search)."""
        tasks = []
        keys: list[str] = []
        for ext, item in results.items():
            if item.status != "available" or item.price_inr is not None:
                continue
            keys.append(ext)
            tasks.append(self._registration_service.check_openprovider_domain(item.domain))

        if not tasks:
            return

        checks = await asyncio.gather(*tasks, return_exceptions=True)
        for ext, check in zip(keys, checks):
            if isinstance(check, Exception):
                logger.warning(
                    "AI domain price fetch failed domain=%s: %s",
                    results[ext].domain,
                    check,
                )
                continue
            if check.status == "available":
                unit = float(check.unitPrice or check.price or 0)
                if unit > 0:
                    results[ext].price_inr = unit
