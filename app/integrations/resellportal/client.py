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

logger = logging.getLogger(__name__)

UNCONFIGURED_ADMIN_MESSAGE = (
    "ResellPortal API credentials have not been configured yet. "
    "API keys will be added after the provider wallet is funded and API access is generated."
)


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

    def _create_client(self, user_email: str, user_id: str) -> str | int | None:
        """Resolve (or create) a ResellPortal client and return the client_id.

        Client creation intentionally bypasses *test_mode* payload injection.
        When ``test_mode`` is present in the request body, ResendPortal returns a
        synthetic ``test_cli_...`` identifier that is valid only within the
        single request and cannot be reused for order creation.  Creating a
        real (numeric) client — then sending ``test_mode`` on the subsequent
        /orders call — gives us a usable ``client_id`` while still exercising
        the test-mode provisioning path on the orders endpoint.

        If a client with the same email already exists, it is reused rather
        than creating a duplicate.
        """
        if not self.is_configured():
            res = MockResellPortalAPI.create_client(user_email=user_email, user_id=user_id, test_mode=self.is_test_mode())
            return res.get("client_id")

        headers = self.get_auth_headers()

        # 1. Look up an existing client by email to avoid duplicates.
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(
                    f"{self.api_base}/clients",
                    headers=headers,
                    params={"email": user_email},
                )
                if resp.status_code == 200:
                    clients = resp.json().get("clients") or []
                    if clients:
                        existing_id = clients[0].get("id")
                        if existing_id is not None:
                            logger.info("ResendPortal reusing existing client_id=%s for email=%s", existing_id, user_email)
                            return existing_id
        except Exception as err:
            logger.warning("ResendPortal client lookup failed for email=%s: %s", user_email, err)

        # 2. Create a new client (no test_mode in body).
        payload = {
            "name": user_email,
            "email": user_email,
        }
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(
                    f"{self.api_base}/clients",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                res_json = response.json()
                return res_json.get("client_id")
        except Exception as err:
            logger.warning("ResendPortal client creation failed for user_id=%s: %s", user_id, err)
            return None

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
        # Also include skip_client_email for provider order activation flows where supported.
        if method in ("POST", "DELETE") and self.is_test_mode():
            data["test_mode"] = True
            if method == "POST":
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
        except Exception as err:
            logger.warning("ResellPortal HTTP Request Error [%s %s]: %s", method, endpoint, err)
            # Fallback gracefully to mock response rather than throwing 500 error
            return {
                "success": False,
                "error": str(err),
                "configured": self.is_configured(),
                "fallback": True,
            }

    def get_wallet_balance(self) -> dict[str, Any]:
        """GET /wallet/balance - Fetch live wallet balance."""
        if not self.is_configured():
            logger.info("ResellPortal API unconfigured. Returning mock wallet balance.")
            res = MockResellPortalAPI.get_wallet_balance()
            res["configured"] = False
            res["message"] = UNCONFIGURED_ADMIN_MESSAGE
            return res

        res = self._make_request("GET", "wallet/balance")
        if not res.get("success") and res.get("fallback"):
            mock_res = MockResellPortalAPI.get_wallet_balance()
            mock_res["configured"] = True
            mock_res["live_error"] = res.get("error")
            return mock_res
        return res

    def get_product_catalog(self) -> list[dict[str, Any]]:
        """GET /catalog - Fetch product catalog from provider."""
        if not self.is_configured():
            return MockResellPortalAPI.get_catalog()
        res = self._make_request("GET", "catalog")
        if isinstance(res, list):
            return res
        return MockResellPortalAPI.get_catalog()

    def get_service_status(self, service_slug: str) -> dict[str, Any]:
        """GET /services/{slug} - Fetch service status."""
        if not self.is_configured():
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
            return {
                "success": status in {"ACTIVE", "PENDING", "PROVISIONING_PENDING"},
                "status": status,
                "needs_reconciliation": True,
                "provider_order_id": matching_order.get("provider_order_id") or matching_order.get("order_id"),
                "provider_subscription_id": matching_order.get("provider_subscription_id") or matching_order.get("subscription_id"),
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
            res["configured"] = False
            return res

        payload = {
            "product_key": product_key or service_slug,
            "service_slug": service_slug,
            "service_name": service_name,
            "plan_code": plan_code,
            "billing_cycle": billing_cycle,
            "user_email": user_email,
            "user_id": user_id,
        }

        # ResendPortal POST /orders requires a client_id.  Create one first.
        resolved_client_id = self._create_client(user_email, user_id)
        if resolved_client_id is not None:
            payload["client_id"] = resolved_client_id

        if order_parameters:
            payload.update(order_parameters)

        # ResendPortal API expects array-typed fields like ai_tools to be arrays.
        if "ai_tools" in payload and isinstance(payload["ai_tools"], str):
            payload["ai_tools"] = [payload["ai_tools"]]

        res = self._make_request("POST", "orders", json_data=payload)
        # Do not convert network/timeout/fallback errors into a fake successful order.
        if not res.get("success") or res.get("fallback"):
            logger.warning(
                "ResellPortal provision request did not yield confirmed success. service=%s user_id=%s product_key=%s reason=%s",
                service_slug,
                user_id,
                product_key,
                res.get("error") or "unknown",
            )
            return {
                "success": False,
                "status": "PROVISIONING_PENDING",
                "provider_order_id": None,
                "provider_subscription_id": None,
                "current_period_start": None,
                "current_period_end": None,
                "credentials": {},
                "error": res.get("error") or "ResellPortal request did not confirm provisioning.",
                "needs_reconciliation": True,
                "configured": True,
            }

        res.setdefault("provider_order_id", res.get("order_id") or res.get("provider_order_id") or f"RSP-ORD-{user_id[:8]}")
        res.setdefault("provider_subscription_id", res.get("subscription_id") or res.get("provider_subscription_id") or res.get("service_id") or f"RSP-SUB-{user_id[:8]}")
        res.setdefault("credentials", res.get("client_credentials", {}))
        if not res.get("current_period_start"):
            res["current_period_start"] = datetime.now(timezone.utc)
        if not res.get("current_period_end"):
            days = 365 if billing_cycle == "annually" else 30
            res["current_period_end"] = datetime.now(timezone.utc) + timedelta(days=days)
        if "status" not in res:
            res["status"] = "PROVISIONING_PENDING"
        if "current_period_start" not in res:
            res["current_period_start"] = None
        if "current_period_end" not in res:
            res["current_period_end"] = None
        return res

    def renew_subscription(self, provider_sub_id: str, billing_cycle: str) -> dict[str, Any]:
        """Renew active subscription with provider."""
        logger.info("ResellPortal Renew Request | sub_id=%s cycle=%s configured=%s", provider_sub_id, billing_cycle, self.is_configured())
        if not self.is_configured():
            res = MockResellPortalAPI.renew_subscription(provider_sub_id, billing_cycle, test_mode=self.is_test_mode())
            res["configured"] = False
            return res

        payload = {"billing_cycle": billing_cycle}
        res = self._make_request("POST", f"subscriptions/{provider_sub_id}/renew", json_data=payload)
        if not res.get("success") or res.get("fallback"):
            return MockResellPortalAPI.renew_subscription(provider_sub_id, billing_cycle, test_mode=self.is_test_mode())
        return res

    def upgrade_subscription(self, provider_sub_id: str, new_plan_code: str) -> dict[str, Any]:
        """Upgrade/downgrade plan with provider."""
        logger.info("ResellPortal Plan Upgrade Request | sub_id=%s new_plan=%s configured=%s", provider_sub_id, new_plan_code, self.is_configured())
        if not self.is_configured():
            res = MockResellPortalAPI.upgrade_subscription(provider_sub_id, new_plan_code, test_mode=self.is_test_mode())
            res["configured"] = False
            return res

        payload = {"new_plan_code": new_plan_code}
        res = self._make_request("POST", f"subscriptions/{provider_sub_id}/upgrade", json_data=payload)
        if not res.get("success") or res.get("fallback"):
            return MockResellPortalAPI.upgrade_subscription(provider_sub_id, new_plan_code, test_mode=self.is_test_mode())
        return res

    def cancel_subscription(self, provider_sub_id: str) -> dict[str, Any]:
        """Cancel active subscription with provider."""
        logger.info("ResellPortal Cancellation Request | sub_id=%s configured=%s", provider_sub_id, self.is_configured())
        if not self.is_configured():
            res = MockResellPortalAPI.cancel_subscription(provider_sub_id, test_mode=self.is_test_mode())
            res["configured"] = False
            return res

        res = self._make_request("DELETE", f"subscriptions/{provider_sub_id}")
        if not res.get("success") or res.get("fallback"):
            return MockResellPortalAPI.cancel_subscription(provider_sub_id, test_mode=self.is_test_mode())
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
