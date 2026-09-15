"""ResellPortal REST API Wrapper Client.

Provides a 100% white-labelled abstraction layer over provider APIs.
Users and frontends interact only with CoBrother; all provider calls, token exchanges,
and service provisioning occur server-side.

Supports:
1. Blank/Unconfigured credentials state gracefully (using MockResellPortalAPI fallback).
2. Live HTTP calls to RESELLPORTAL_BASE_URL when API credentials are provided.
3. Automatic attachment of `{"test_mode": true}` for all POST and DELETE calls when in test mode.
4. GET requests execution without test_mode.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.integrations.resellportal.mock_resellportal_api import MockResellPortalAPI
from app.service.technology.provider_access import (
    credential_log_fields,
    extract_provider_credentials,
    merge_provider_credentials,
    portal_account_from_provider_client,
    real_provider_order_id,
    real_provider_service_id,
)

logger = logging.getLogger(__name__)

UNCONFIGURED_ADMIN_MESSAGE = (
    "ResellPortal API credentials have not been configured yet. "
    "API keys will be added after the provider wallet is funded and API access is generated."
)


def _production_environment() -> bool:
    return str(getattr(settings, "ENVIRONMENT", "") or "").strip().lower() == "production"


def _production_live_resellportal_enabled() -> bool:
    return (
        not _production_environment()
        or (
            bool(getattr(settings, "RESELLPORTAL_ALLOW_LIVE", False))
            and not bool(getattr(settings, "RESELLPORTAL_TEST_MODE", True))
        )
    )


def _production_live_disabled_response() -> dict[str, Any]:
    return {
        "success": False,
        "status": "PROVISIONING_PENDING",
        "provider_order_id": None,
        "provider_subscription_id": None,
        "service_id": None,
        "credentials": {},
        "error": "Live ResellPortal provisioning is not enabled for production.",
        "needs_reconciliation": True,
        "configured": bool(settings.resellportal_configured()),
    }


def _simulated_test_order_response(res: dict[str, Any], *, user_id: str) -> dict[str, Any]:
    service_id = real_provider_service_id(res, user_id=user_id)
    order_id = real_provider_order_id(res, user_id=user_id)
    return {
        "success": True,
        "status": "TEST_SIMULATED",
        "provider_order_id": order_id,
        "provider_subscription_id": service_id,
        "service_id": service_id,
        "current_period_start": None,
        "current_period_end": None,
        "credentials": {},
        "message": (
            "ResellPortal test_mode order was simulated by the provider; "
            "no real service is customer-accessible."
        ),
        "needs_reconciliation": False,
        "configured": True,
        "test_mode": True,
        "test_only": True,
        "simulated": True,
    }


def normalize_provision_response(
    res: dict[str, Any],
    *,
    user_id: str,
    billing_cycle: str,
    request_test_mode: bool = False,
) -> dict[str, Any]:
    """Map a live POST /orders body onto local fields without fabricating IDs.

    Confirmed success shape::

        {"success": true, "status": "ACTIVE", "service_id": "...",
         "credentials": {"access_token": "...", "username": "..."}}

    ``service_id`` is stored as ``provider_subscription_id`` (existing renew /
    upgrade / cancel identifier). Missing real service_id on an ACTIVE claim
    is treated as incomplete provisioning, never as a fake RSP-SUB id.
    """
    if not res.get("success") or res.get("fallback"):
        logger.warning(
            "ResellPortal provision request did not yield confirmed success. user_id=%s reason=%s",
            user_id,
            res.get("error") or "unknown",
        )
        return {
            "success": False,
            "status": "PROVISIONING_PENDING",
            "provider_order_id": real_provider_order_id(res, user_id=user_id),
            "provider_subscription_id": None,
            "service_id": None,
            "current_period_start": None,
            "current_period_end": None,
            "credentials": {},
            "error": res.get("error") or "ResellPortal request did not confirm provisioning.",
            "needs_reconciliation": True,
            "configured": True,
        }

    if request_test_mode or bool(res.get("test_mode")):
        return _simulated_test_order_response(res, user_id=user_id)

    service_id = real_provider_service_id(res, user_id=user_id)
    order_id = real_provider_order_id(res, user_id=user_id)
    credentials = extract_provider_credentials(res)
    status = str(res.get("status") or "").strip().upper() or "PROVISIONING_PENDING"

    logger.info(
        "ResellPortal provision mapped user=%s status=%s has_service_id=%s has_order_id=%s %s",
        user_id,
        status,
        bool(service_id),
        bool(order_id),
        credential_log_fields(credentials),
    )

    if status == "ACTIVE" and not service_id:
        logger.warning(
            "ResellPortal provision missing real service_id; treating as incomplete. user=%s",
            user_id,
        )
        return {
            "success": False,
            "status": "PROVISIONING_PENDING",
            "provider_order_id": order_id,
            "provider_subscription_id": None,
            "service_id": None,
            "current_period_start": None,
            "current_period_end": None,
            "credentials": {},
            "error": "Provider did not return a real service_id.",
            "needs_reconciliation": True,
            "configured": True,
        }

    start = res.get("current_period_start")
    end = res.get("current_period_end")
    if not start:
        start = datetime.now(timezone.utc)
    if not end:
        days = 365 if billing_cycle == "annually" else 30
        end = datetime.now(timezone.utc) + timedelta(days=days)

    return {
        "success": True,
        "status": status,
        "provider_order_id": order_id,
        "provider_subscription_id": service_id,
        "service_id": service_id,
        "current_period_start": start,
        "current_period_end": end,
        "credentials": credentials,
        "configured": True,
    }


class ResellPortalClient:
    """Option C Full REST API Integration Client for ResellPortal."""

    def __init__(
        self,
        api_base: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        self.api_base = (
            api_base
            or getattr(settings, "RESELLPORTAL_BASE_URL", None)
            or "https://panel.resellportal.com/wp-json/resellportal/v1"
        ).rstrip("/")
        self.api_key = api_key if api_key is not None else getattr(settings, "RESELLPORTAL_API_KEY", "")
        self.api_secret = api_secret if api_secret is not None else getattr(settings, "RESELLPORTAL_API_SECRET", "")

    def is_configured(self) -> bool:
        """Returns True if API key and secret are non-empty."""
        return bool((self.api_key or "").strip() and (self.api_secret or "").strip())

    def is_test_mode(self) -> bool:
        """Returns True if operating in test mode (attaching test_mode: true to POST/DELETE calls)."""
        return settings.resellportal_test_mode()

    def get_auth_headers(self) -> dict[str, str]:
        """Generate request headers with API key and secret."""
        return {
            "X-API-Key": self.api_key or "",
            "X-API-Secret": self.api_secret or "",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def create_portal_client(
        self,
        *,
        user_email: str,
        user_id: str,
        portal_password: str | None = None,
    ) -> dict[str, Any]:
        """POST /clients and return normalized portal-account fields.

        The confirmed provider contract only documents POST /clients. Reuse
        must therefore come from our own encrypted, persisted customer state.
        """
        if not self.is_configured():
            if _production_environment():
                return {
                    "success": False,
                    "error": "ResellPortal API credentials are not configured.",
                    "configured": False,
                }
            res = MockResellPortalAPI.create_client(
                user_email=user_email,
                user_id=user_id,
                test_mode=self.is_test_mode(),
            )
            normalized = portal_account_from_provider_client(res)
            normalized.update(
                {
                    "success": bool(normalized.get("provider_client_id")),
                    "configured": False,
                    "is_mock": True,
                    "test_mode": self.is_test_mode(),
                    "test_only": True,
                }
            )
            return normalized

        if not _production_live_resellportal_enabled():
            return {
                "success": False,
                "error": "Live ResellPortal client creation is not enabled for production.",
                "configured": True,
            }

        payload = {
            "name": user_email,
            "email": user_email,
        }
        if portal_password:
            payload["password"] = portal_password
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(
                    f"{self.api_base}/clients",
                    headers=self.get_auth_headers(),
                    json=payload,
                )
                response.raise_for_status()
                res_json = response.json()
                normalized = portal_account_from_provider_client(res_json if isinstance(res_json, dict) else {})
                normalized.update({"success": bool(normalized.get("provider_client_id")), "configured": True})
                if not normalized["success"]:
                    normalized["error"] = "ResellPortal did not return a client_id from POST /clients."
                return normalized
        except Exception as err:
            logger.warning("ResellPortal client creation failed for user_id=%s: %s", user_id, type(err).__name__)
            return {
                "success": False,
                "error": type(err).__name__,
                "configured": True,
            }

    def _create_client(self, user_email: str, user_id: str) -> str | int | None:
        """Backward-compatible POST /clients wrapper returning the client_id.

        Client creation intentionally bypasses *test_mode* payload injection.
        When ``test_mode`` is present in the request body, ResendPortal returns a
        synthetic ``test_cli_...`` identifier that is valid only within the
        single request and cannot be reused for order creation.  Creating a
        real (numeric) client — then sending ``test_mode`` on the subsequent
        /orders call — gives us a usable ``client_id`` while still exercising
        the test-mode provisioning path on the orders endpoint.
        """
        res = self.create_portal_client(user_email=user_email, user_id=user_id)
        return res.get("provider_client_id")

    def _make_request(
        self,
        method: str,
        endpoint: str,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Internal HTTP request wrapper with test_mode payload injection for POST/DELETE."""
        url = f"{self.api_base}/{endpoint.lstrip('/')}"
        method = method.upper()

        data = dict(json_data) if json_data else {}

        # Automatically inject test_mode for POST/DELETE in test mode.
        if method in ("POST", "DELETE") and self.is_test_mode():
            data["test_mode"] = True
        if method == "POST" and endpoint.strip("/").lower() == "orders":
            data["skip_client_email"] = True

        headers = self.get_auth_headers()

        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data if method in ("POST", "PUT", "PATCH", "DELETE") and data else None,
                    params=params,
                )
                response.raise_for_status()
                res_json = response.json()
                if isinstance(res_json, dict):
                    res_json["configured"] = True
                return res_json
        except httpx.HTTPStatusError as err:
            logger.warning(
                "ResellPortal HTTP Request Error [%s %s]: status=%s",
                method,
                endpoint,
                err.response.status_code if err.response is not None else "unknown",
            )
            return {
                "success": False,
                "error": f"HTTP {err.response.status_code}" if err.response is not None else type(err).__name__,
                "configured": self.is_configured(),
                "fallback": True,
            }
        except Exception as err:
            logger.warning(
                "ResellPortal HTTP Request Error [%s %s]: %s",
                method,
                endpoint,
                type(err).__name__,
            )
            return {
                "success": False,
                "error": type(err).__name__,
                "configured": self.is_configured(),
                "fallback": True,
            }

    def get_wallet_balance(self) -> dict[str, Any]:
        """GET /wallet/balance - Fetch live wallet balance."""
        if not self.is_configured():
            if _production_environment():
                return {
                    "success": False,
                    "configured": False,
                    "message": UNCONFIGURED_ADMIN_MESSAGE,
                }
            logger.info("ResellPortal API unconfigured. Returning mock wallet balance.")
            res = MockResellPortalAPI.get_wallet_balance()
            res["configured"] = False
            res["message"] = UNCONFIGURED_ADMIN_MESSAGE
            return res

        res = self._make_request("GET", "wallet/balance")
        if not res.get("success") and res.get("fallback"):
            if _production_environment():
                return res
            mock_res = MockResellPortalAPI.get_wallet_balance()
            mock_res["configured"] = True
            mock_res["live_error"] = res.get("error")
            return mock_res
        return res

    def get_product_catalog(self) -> list[dict[str, Any]]:
        """GET /catalog - Fetch product catalog from provider."""
        if not self.is_configured():
            if _production_environment():
                return []
            return MockResellPortalAPI.get_catalog()
        res = self._make_request("GET", "catalog")
        if isinstance(res, list):
            return res
        if _production_environment():
            return []
        return MockResellPortalAPI.get_catalog()

    def get_service_status(self, service_slug: str) -> dict[str, Any]:
        """GET /services/{slug} - Fetch service status."""
        if not self.is_configured():
            if _production_environment():
                return {
                    "success": False,
                    "configured": False,
                    "error": "ResellPortal API credentials are not configured.",
                }
            res = MockResellPortalAPI.get_service_status(service_slug)
            res["configured"] = False
            return res
        return self._make_request("GET", f"services/{service_slug}")

    def list_orders(self, *, user_id: str | None = None, product_key: str | None = None) -> list[dict[str, Any]]:
        """GET /orders listing for reconciliation and duplicate-order checks."""
        if not self.is_configured():
            return []
        params: dict[str, Any] = {}
        if user_id:
            params["user_id"] = user_id
        if product_key:
            params["product_key"] = product_key
        res = self._make_request("GET", "orders", params=params)
        if isinstance(res, dict) and res.get("orders"):
            return list(res.get("orders") or [])
        if isinstance(res, list):
            return res
        return []

    def find_matching_order(
        self,
        *,
        service_slug: str,
        user_id: str,
        product_key: str | None = None,
        user_email: str | None = None,
        plan_code: str | None = None,
        billing_cycle: str | None = None,
    ) -> dict[str, Any] | None:
        """Find an existing provider order matching as many reliable identifiers as possible.

        ResellPortal's ``POST /orders`` has NO idempotency, so a retry must
        NEVER blindly submit another order. Before creating a new order the
        caller must look up existing orders via the confirmed ``GET /orders``
        endpoint and match on every reliable identifier available:
        CoBrother user id, product key, service slug, plan, billing cycle,
        and customer email. Returns the best match or None.
        """
        orders = self.list_orders(user_id=user_id, product_key=product_key)
        candidates: list[dict[str, Any]] = []
        for order in orders:
            if product_key and str(order.get("product_key") or "").lower() != str(product_key).lower():
                continue
            if service_slug and str(order.get("service_slug") or "").lower() != service_slug.lower():
                continue
            if user_email and str(order.get("user_email") or "").lower() != str(user_email).lower():
                continue
            candidates.append(order)
        if not candidates:
            return None
        if plan_code or billing_cycle:
            for order in candidates:
                if plan_code and str(order.get("plan_code") or "").lower() != str(plan_code).lower():
                    continue
                if billing_cycle and str(order.get("billing_cycle") or "").lower() != str(billing_cycle).lower():
                    continue
                return order
        return candidates[0]

    def reconcile_pending_provisioning(
        self,
        *,
        service_slug: str,
        user_id: str,
        product_key: str | None = None,
        user_email: str | None = None,
        plan_code: str | None = None,
        billing_cycle: str | None = None,
    ) -> dict[str, Any]:
        """Check provider state (GET /orders only) before any provisioning retry.

        Never fabricates a successful order and never assumes a service-status
        endpoint exists. If a matching order is found it is adopted (returned
        with its provider status) — the caller must NOT create another order.
        """
        if not self.is_configured():
            return {
                "success": False,
                "status": "PROVISIONING_PENDING",
                "needs_reconciliation": True,
                "provider_order_id": None,
                "provider_subscription_id": None,
                "reconciled": False,
            }

        matching_order = self.find_matching_order(
            service_slug=service_slug,
            user_id=user_id,
            product_key=product_key,
            user_email=user_email,
            plan_code=plan_code,
            billing_cycle=billing_cycle,
        )

        if matching_order:
            status = str(matching_order.get("status") or "PENDING").upper()
            service_id = real_provider_service_id(matching_order, user_id=user_id)
            return {
                "success": status in {"ACTIVE", "PENDING", "PROVISIONING_PENDING"},
                "status": status,
                "needs_reconciliation": True,
                "provider_order_id": real_provider_order_id(matching_order, user_id=user_id),
                "provider_subscription_id": service_id,
                "service_id": service_id,
                "credentials": extract_provider_credentials(matching_order),
                "reconciled": True,
            }

        return {
            "success": False,
            "status": "PROVISIONING_PENDING",
            "needs_reconciliation": True,
            "provider_order_id": None,
            "provider_subscription_id": None,
            "reconciled": False,
        }

    def provision_service(
        self,
        service_slug: str,
        service_name: str,
        plan_code: str,
        billing_cycle: str,
        user_email: str,
        user_id: str,
        product_key: str | None = None,
        order_parameters: dict[str, Any] | None = None,
        provider_client_id: str | int | None = None,
        portal_account: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Activate a ResellPortal technology service through POST /orders.

        The provider confirms the activation endpoint is POST /orders rather than
        POST /services/activate. The endpoint accepts product_key plus any required
        product-specific parameters such as ai_tools, business_name, or storage_plan.
        """
        logger.info(
            "ResellPortal Provisioning Request | service=%s product_key=%s plan=%s cycle=%s user=%s configured=%s test_mode=%s",
            service_slug,
            product_key or service_slug,
            plan_code,
            billing_cycle,
            user_id,
            self.is_configured(),
            self.is_test_mode(),
        )

        if not self.is_configured():
            if _production_environment():
                return {
                    "success": False,
                    "status": "PROVISIONING_PENDING",
                    "provider_order_id": None,
                    "provider_subscription_id": None,
                    "service_id": None,
                    "credentials": {},
                    "error": "ResellPortal API credentials are not configured.",
                    "needs_reconciliation": True,
                    "configured": False,
                }
            res = MockResellPortalAPI.provision_service(
                service_slug=service_slug,
                service_name=service_name,
                plan_code=plan_code,
                billing_cycle=billing_cycle,
                user_email=user_email,
                user_id=user_id,
                test_mode=self.is_test_mode(),
                product_key=product_key,
                order_parameters=order_parameters,
            )
            normalized = normalize_provision_response(
                res,
                user_id=user_id,
                billing_cycle=billing_cycle,
                request_test_mode=self.is_test_mode(),
            )
            normalized["credentials"] = merge_provider_credentials(
                portal_account,
                normalized.get("credentials") if isinstance(normalized.get("credentials"), dict) else {},
            )
            if normalized.get("simulated") and isinstance(normalized.get("credentials"), dict):
                normalized["credentials"] = merge_provider_credentials(
                    normalized["credentials"],
                    {"test_mode": True, "test_only": True, "simulated": True},
                )
            normalized["configured"] = False
            normalized["test_mode"] = self.is_test_mode()
            return normalized

        if not _production_live_resellportal_enabled():
            return _production_live_disabled_response()

        payload = {
            "product_key": product_key or service_slug,
            "service_slug": service_slug,
            "service_name": service_name,
            "plan_code": plan_code,
            "billing_cycle": billing_cycle,
            "user_email": user_email,
            "user_id": user_id,
        }

        if provider_client_id is None:
            return {
                "success": False,
                "status": "PROVISIONING_PENDING",
                "provider_order_id": None,
                "provider_subscription_id": None,
                "service_id": None,
                "credentials": {},
                "error": "ResellPortal client_id is required before order provisioning.",
                "needs_reconciliation": True,
                "configured": True,
            }
        payload["client_id"] = provider_client_id

        if order_parameters:
            payload.update(order_parameters)

        # ResendPortal API expects array-typed fields like ai_tools to be arrays.
        if "ai_tools" in payload and isinstance(payload["ai_tools"], str):
            payload["ai_tools"] = [payload["ai_tools"]]

        res = self._make_request("POST", "orders", json_data=payload)
        normalized = normalize_provision_response(
            res,
            user_id=user_id,
            billing_cycle=billing_cycle,
            request_test_mode=self.is_test_mode(),
        )
        if normalized.get("credentials") or portal_account:
            normalized["credentials"] = merge_provider_credentials(
                portal_account,
                normalized.get("credentials") if isinstance(normalized.get("credentials"), dict) else {},
            )
        if normalized.get("simulated") and isinstance(normalized.get("credentials"), dict):
            normalized["credentials"] = merge_provider_credentials(
                normalized["credentials"],
                {"test_mode": True, "test_only": True, "simulated": True},
            )
        return normalized

    def renew_subscription(self, provider_sub_id: str, billing_cycle: str) -> dict[str, Any]:
        """Renew active subscription with provider."""
        logger.info("ResellPortal Renew Request | sub_id=%s cycle=%s configured=%s", provider_sub_id, billing_cycle, self.is_configured())
        if not self.is_configured():
            if _production_environment():
                return {
                    "success": False,
                    "error": "ResellPortal API credentials are not configured.",
                    "configured": False,
                }
            res = MockResellPortalAPI.renew_subscription(provider_sub_id, billing_cycle, test_mode=self.is_test_mode())
            res["configured"] = False
            return res

        if not _production_live_resellportal_enabled():
            return {
                "success": False,
                "error": "Live ResellPortal renewals are not enabled for production.",
                "configured": True,
            }

        payload = {"billing_cycle": billing_cycle}
        res = self._make_request("POST", f"subscriptions/{provider_sub_id}/renew", json_data=payload)
        return res

    def upgrade_subscription(self, provider_sub_id: str, new_plan_code: str) -> dict[str, Any]:
        """Upgrade/downgrade plan with provider."""
        logger.info("ResellPortal Plan Upgrade Request | sub_id=%s new_plan=%s configured=%s", provider_sub_id, new_plan_code, self.is_configured())
        if not self.is_configured():
            if _production_environment():
                return {
                    "success": False,
                    "error": "ResellPortal API credentials are not configured.",
                    "configured": False,
                }
            res = MockResellPortalAPI.upgrade_subscription(provider_sub_id, new_plan_code, test_mode=self.is_test_mode())
            res["configured"] = False
            return res

        if not _production_live_resellportal_enabled():
            return {
                "success": False,
                "error": "Live ResellPortal upgrades are not enabled for production.",
                "configured": True,
            }

        payload = {"new_plan_code": new_plan_code}
        res = self._make_request("POST", f"subscriptions/{provider_sub_id}/upgrade", json_data=payload)
        return res

    def cancel_subscription(self, provider_sub_id: str) -> dict[str, Any]:
        """Cancel active subscription with provider."""
        logger.info("ResellPortal Cancellation Request | sub_id=%s configured=%s", provider_sub_id, self.is_configured())
        if not self.is_configured():
            if _production_environment():
                return {
                    "success": False,
                    "error": "ResellPortal API credentials are not configured.",
                    "configured": False,
                }
            res = MockResellPortalAPI.cancel_subscription(provider_sub_id, test_mode=self.is_test_mode())
            res["configured"] = False
            return res

        if not _production_live_resellportal_enabled():
            return {
                "success": False,
                "error": "Live ResellPortal cancellations are not enabled for production.",
                "configured": True,
            }

        res = self._make_request("DELETE", f"subscriptions/{provider_sub_id}")
        return res

    def handle_webhook(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle incoming provider webhook notifications."""
        logger.info("ResellPortal Webhook Event Received | event=%s", event_type)
        return {"processed": True, "event": event_type}


_client_instance: ResellPortalClient | None = None


def get_resellportal_client() -> ResellPortalClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = ResellPortalClient()
    return _client_instance
