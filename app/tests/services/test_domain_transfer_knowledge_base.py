"""Tests for CoBrother domain transfer AI knowledge base."""

from app.service.ai.ai_context_builder import AiContextBuilder
from app.service.ai.domain_transfer_knowledge_base import (
    build_deterministic_response,
    build_knowledge_context,
    detect_transfer_topic,
    is_domain_transfer_question,
)


def test_is_domain_transfer_question_detects_payout_and_auth_code():
    assert is_domain_transfer_question("Why is my payout pending?")
    assert is_domain_transfer_question("What is an Auth Code?")
    assert is_domain_transfer_question("How does domain transfer work after purchase?")


def test_is_domain_transfer_question_ignores_unrelated_marketplace_search():
    assert not is_domain_transfer_question("Show me premium AI domain listings")


def test_detect_transfer_topic():
    assert detect_transfer_topic("What is an EPP code?") == "auth_code"
    assert detect_transfer_topic("What is the 15% commission?") == "commission"
    assert detect_transfer_topic("When will I get paid?") == "payout"


def test_commission_example():
    example = build_knowledge_context()["commission"]["example"]
    assert example["sale_price"] == 1000
    assert example["commission"] == 150
    assert example["seller_receives"] == 850


def test_build_deterministic_response_auth_code():
    response = build_deterministic_response("What is an Auth Code?")
    assert response is not None
    assert "Auth Code" in response
    assert "EPP" in response


def test_build_deterministic_response_commission():
    response = build_deterministic_response("How much commission does HubRegistrar charge?")
    assert response is not None
    assert "15%" in response
    assert "850" in response


def test_build_deterministic_response_payout_pending_status():
    response = build_deterministic_response("What does payout pending mean?")
    assert response is not None
    assert "Payout Pending" in response or "payout" in response.lower()


def test_ai_context_builder_marks_domain_transfer_requests():
    builder = AiContextBuilder.__new__(AiContextBuilder)
    request_type = AiContextBuilder.detect_request_type(builder, "When will I receive my domain?", "broker")
    intent = AiContextBuilder.detect_intent(builder, "When will I receive my domain?", "broker")
    assert request_type == "domain_transfer"
    assert intent == "domain_transfer"


def test_ai_context_builder_system_prompt_includes_transfer_kb():
    builder = AiContextBuilder.__new__(AiContextBuilder)
    prompt = AiContextBuilder.system_prompt(
        builder,
        {"mode": "broker", "domain_transfer_kb": build_knowledge_context()},
    )
    assert "COBROTHER DOMAIN TRANSFER KNOWLEDGE BASE" in prompt
    assert "escrow-style" in prompt.lower() or "escrow" in prompt.lower()
    assert "15%" in prompt
