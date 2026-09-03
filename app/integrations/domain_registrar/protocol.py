"""Registrar provider contract (OpenProvider)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DomainRegistrarClient(Protocol):
    def is_configured(self) -> bool: ...

    def is_sandbox(self) -> bool: ...

    async def check_domain(self, name: str, extension_no_dot: str) -> dict[str, Any]: ...

    def is_free(self, check_result: dict[str, Any]) -> bool: ...

    async def get_create_price(
        self,
        name: str,
        extension_no_dot: str,
        *,
        period: int = 1,
        classkey: str | None = None,
    ) -> dict[str, Any]: ...

    def extract_create_price_details(
        self,
        quote: dict[str, Any],
        *,
        source_hint: str | None = None,
    ) -> tuple[float, str | None, str]: ...

    def resolve_registration_period(self, requested: int, extension_no_dot: str) -> int: ...

    async def create_customer(self, contact: dict[str, Any]) -> str: ...

    async def register_domain(
        self,
        name: str,
        extension_no_dot: str,
        handle: str,
        period_years: int,
        *,
        contact: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def friendly_error_from_body(self, raw: str) -> str: ...

    def validate_runtime(self, *, for_live_checkout: bool = False) -> dict: ...

    async def get_domain_all_details(self, domain_id: str) -> dict: ...

    async def lookup_order_id_by_domain(self, fqdn: str) -> str | None: ...

    async def resend_raa_verification(self, *, email: str, handle: str) -> bool: ...

    def is_registration_confirmed(self, details: dict[str, Any]) -> bool: ...

    def parse_raa_verification_status(self, details: dict[str, Any]) -> str: ...

    def parse_expiry_from_details(self, details: dict[str, Any]) -> datetime | None: ...

    def order_details_current_status(self, details: dict[str, Any]) -> str: ...

    def default_nameservers(self) -> list[str]: ...

    def parse_nameservers_from_details(self, details: dict[str, Any]) -> list[str]: ...

    def is_platform_nameserver_set(self, hosts: list[str]) -> bool: ...
