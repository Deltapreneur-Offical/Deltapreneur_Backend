"""Tests for context-aware domain transfer AI support."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from app.service.ai.domain_transfer_knowledge_base import (
    CONTEXT_UNAVAILABLE_MESSAGE,
    build_context_aware_response,
    needs_live_transfer_context,
)
from app.service.ai.transfer_context_service import TransferContextService


def test_needs_live_transfer_context_detects_workflow_questions():
    assert needs_live_transfer_context("What should I do next?")
    assert needs_live_transfer_context("Where do I enter the auth code?")
    assert needs_live_transfer_context("I cannot see the auth code")
    assert not needs_live_transfer_context("Show me premium domains")


def test_build_context_aware_response_unavailable():
    response = build_context_aware_response(
        "What should I do next?",
        {"available": False},
    )
    assert response == CONTEXT_UNAVAILABLE_MESSAGE


def test_build_context_aware_response_otp_required():
    ctx = {
        "available": True,
        "domain_fqdn": "example.com",
        "user_role": "buyer",
        "transfer_status": "AUTH_CODE_AVAILABLE",
        "auth_code_status": {"status": "available", "has_code": True},
        "otp_status": {"required_for_reveal": True, "verified": False, "pending": False},
        "next_step": "Verify OTP to reveal the authorization code.",
    }
    response = build_context_aware_response("I got the auth code. What do I do now?", ctx)
    assert response is not None
    assert "OTP" in response
    assert "example.com" in response


def test_build_context_aware_response_auth_code_ready():
    ctx = {
        "available": True,
        "domain_fqdn": "example.com",
        "user_role": "buyer",
        "transfer_status": "AUTH_CODE_AVAILABLE",
        "auth_code_status": {"status": "available", "has_code": True},
        "otp_status": {"required_for_reveal": True, "verified": True, "pending": False},
        "next_step": "Begin transfer at your registrar.",
    }
    response = build_context_aware_response("I received the auth code, what next?", ctx)
    assert response is not None
    assert "authorization code is now available" in response.lower()


def test_build_context_aware_response_registrar_prompt():
    ctx = {
        "available": True,
        "domain_fqdn": "shop.io",
        "user_role": "buyer",
        "transfer_status": "AUTH_CODE_VIEWED",
        "auth_code_status": {"status": "viewed", "has_code": True},
        "otp_status": {"required_for_reveal": True, "verified": True, "pending": False},
        "buyer_target_registrar": None,
        "next_step": "Initiate transfer.",
    }
    response = build_context_aware_response("Where do I enter the auth code?", ctx)
    assert response is not None
    assert "Which registrar" in response


def test_build_context_aware_response_godaddy_steps():
    ctx = {
        "available": True,
        "domain_fqdn": "shop.io",
        "user_role": "buyer",
        "transfer_status": "AUTH_CODE_VIEWED",
        "auth_code_status": {"status": "viewed", "has_code": True},
        "otp_status": {"required_for_reveal": True, "verified": True, "pending": False},
        "buyer_target_registrar": "GoDaddy",
        "next_step": "Initiate transfer.",
    }
    response = build_context_aware_response("Where do I enter the auth code at GoDaddy?", ctx)
    assert response is not None
    assert "GoDaddy" in response
    assert "authorization code" in response.lower()


def test_build_context_aware_response_payment_completed_buyer():
    ctx = {
        "available": True,
        "domain_fqdn": "brand.com",
        "user_role": "buyer",
        "transfer_status": "PAYMENT_COMPLETED",
        "next_step": "Wait for seller to submit auth code.",
    }
    response = build_context_aware_response("What should I do next?", ctx)
    assert response is not None
    assert "seller" in response.lower()


def test_build_context_aware_response_payout_pending_seller():
    ctx = {
        "available": True,
        "domain_fqdn": "brand.com",
        "user_role": "seller",
        "transfer_status": "PAYOUT_PENDING",
        "payout_status": {
            "eligible": True,
            "payout_profile_complete": False,
            "seller_payout_inr": 850,
        },
        "next_step": "Complete payout settings.",
    }
    response = build_context_aware_response("Why is payout pending?", ctx)
    assert response is not None
    assert "Payout Settings" in response or "payout" in response.lower()


@pytest.mark.asyncio
async def test_transfer_context_service_parses_route_transaction_id():
    service = TransferContextService(MagicMock())
    tx_id = uuid.uuid4()
    parsed = service._parse_transaction_id_from_route(f"/purchases/transfers/{tx_id}")
    assert parsed == tx_id


@pytest.mark.asyncio
async def test_transfer_context_service_unauthenticated():
    service = TransferContextService(MagicMock())
    ctx = await service.build_for_user(None, message="What should I do next?")
    assert ctx["available"] is False
    assert ctx["reason"] == "not_authenticated"
