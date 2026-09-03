"""Mock ResellPortal REST API Endpoint Emulator.

Used for local development, testing, and when RESELLPORTAL_API_KEY / RESELLPORTAL_API_SECRET
are blank (prior to provider wallet funding).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any


class MockResellPortalAPI:
    """Emulates ResellPortal REST API responses with 100% white-labelled output."""

    @staticmethod
    def get_wallet_balance() -> dict[str, Any]:
        """Mock GET /wallet/balance endpoint."""
        return {
            "success": True,
            "balance": 145.50,
            "currency": "USD",
            "warning_threshold": 7.00,
            "status": "OK",
            "is_mock": True,
        }

    @staticmethod
    def create_client(
        user_email: str,
        user_id: str,
        test_mode: bool = True,
    ) -> dict[str, Any]:
        """Mock POST /clients endpoint."""
        return {
            "success": True,
            "client_id": f"mock_cli_{secrets.token_hex(4)}",
            "test_mode": test_mode,
            "is_mock": True,
        }

    @staticmethod
    def get_catalog() -> list[dict[str, Any]]:
        """Mock GET /catalog endpoint returning available SaaS products."""
        return [
            {"slug": "ai-business-suite", "name": "AI Business Suite", "category": "AI", "base_price_monthly": 29.0},
            {"slug": "website-builder", "name": "Website Builder", "category": "Business", "base_price_monthly": 15.0},
            {"slug": "crm", "name": "CRM", "category": "Business", "base_price_monthly": 25.0},
            {"slug": "invoice-ai", "name": "Invoice AI", "category": "Productivity", "base_price_monthly": 12.0},
            {"slug": "appointment-booking", "name": "Appointment Booking", "category": "Productivity", "base_price_monthly": 10.0},
            {"slug": "document-signer", "name": "Document Signer", "category": "Productivity", "base_price_monthly": 15.0},
            {"slug": "cloud-storage", "name": "Cloud Storage", "category": "Storage", "base_price_monthly": 19.0},
            {"slug": "business-phone", "name": "Business Phone", "category": "Communication", "base_price_monthly": 20.0},
            {"slug": "vpn", "name": "VPN", "category": "Security", "base_price_monthly": 8.0},
            {"slug": "email-marketing", "name": "Email Marketing", "category": "Marketing", "base_price_monthly": 22.0},
            {"slug": "social-media-automation", "name": "Social Media Automation", "category": "Marketing", "base_price_monthly": 18.0},
            {"slug": "reputation-management", "name": "Reputation Management", "category": "Marketing", "base_price_monthly": 30.0},
            {"slug": "link-in-bio", "name": "Link in Bio", "category": "Marketing", "base_price_monthly": 5.0},
            {"slug": "smm-growth", "name": "SMM Growth", "category": "Marketing", "base_price_monthly": 25.0},
            {"slug": "esim", "name": "eSIM", "category": "Communication", "base_price_monthly": 15.0},
            {"slug": "web-hosting", "name": "Web Hosting", "category": "Hosting", "base_price_monthly": 12.0},
            {"slug": "wordpress-plugin-pack", "name": "WordPress Plugin Pack", "category": "Hosting", "base_price_monthly": 10.0},
        ]

    @staticmethod
    def get_service_status(service_slug: str) -> dict[str, Any]:
        """Mock GET /services/{slug} endpoint."""
        return {
            "success": True,
            "service_slug": service_slug,
            "status": "ACTIVE",
            "health": "HEALTHY",
            "uptime_percent": 99.99,
        }

    @staticmethod
    def provision_service(
        service_slug: str,
        service_name: str,
        plan_code: str,
        billing_cycle: str,
        user_email: str,
        user_id: str,
        test_mode: bool = True,
        product_key: str | None = None,
        order_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Mock POST /services/provision endpoint."""
        provider_order_id = f"RSP-ORD-{secrets.token_hex(4).upper()}"
        provider_sub_id = f"RSP-SUB-{secrets.token_hex(6).upper()}"
        access_token = secrets.token_urlsafe(24)
        instance_id = secrets.token_hex(4)

        # 100% white-labelled URL under CoBrother domain namespace
        white_label_url = f"https://workspace.cobrother.com/app/{service_slug}/{instance_id}?token={access_token}"

        credentials = {
            "access_url": white_label_url,
            "account_id": f"cb_{user_id[:8]}",
            "username": user_email,
            "access_token": access_token,
            "custom_domain_supported": True,
            "provisioned_at": datetime.now(timezone.utc).isoformat(),
            "instructions": f"Access your white-labelled {service_name} dashboard via CoBrother workspace.",
        }

        start_time = datetime.now(timezone.utc)
        days = 365 if billing_cycle == "annually" else 30
        end_time = start_time + timedelta(days=days)

        return {
            "success": True,
            "product_key": product_key or service_slug,
            "order_parameters": dict(order_parameters or {}),
            "provider_order_id": provider_order_id,
            "provider_subscription_id": provider_sub_id,
            "status": "ACTIVE",
            "current_period_start": start_time,
            "current_period_end": end_time,
            "credentials": credentials,
            "test_mode": test_mode,
            "is_mock": True,
        }

    @staticmethod
    def renew_subscription(provider_sub_id: str, billing_cycle: str, test_mode: bool = True) -> dict[str, Any]:
        """Mock POST /subscriptions/{id}/renew endpoint."""
        days = 365 if billing_cycle == "annually" else 30
        new_end = datetime.now(timezone.utc) + timedelta(days=days)
        return {
            "success": True,
            "provider_subscription_id": provider_sub_id,
            "status": "ACTIVE",
            "current_period_end": new_end,
            "renewed_at": datetime.now(timezone.utc).isoformat(),
            "test_mode": test_mode,
            "is_mock": True,
        }

    @staticmethod
    def upgrade_subscription(provider_sub_id: str, new_plan_code: str, test_mode: bool = True) -> dict[str, Any]:
        """Mock POST /subscriptions/{id}/upgrade endpoint."""
        return {
            "success": True,
            "provider_subscription_id": provider_sub_id,
            "plan_code": new_plan_code,
            "status": "ACTIVE",
            "upgraded_at": datetime.now(timezone.utc).isoformat(),
            "test_mode": test_mode,
            "is_mock": True,
        }

    @staticmethod
    def cancel_subscription(provider_sub_id: str, test_mode: bool = True) -> dict[str, Any]:
        """Mock DELETE /subscriptions/{id} endpoint."""
        return {
            "success": True,
            "provider_subscription_id": provider_sub_id,
            "status": "CANCELLED",
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
            "test_mode": test_mode,
            "is_mock": True,
        }
