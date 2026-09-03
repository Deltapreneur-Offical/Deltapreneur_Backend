from app.service.ai.provider import OpenRouterProvider
from app.services.openrouter_service import OpenRouterService


def test_openrouter_provider_sanitizes_google_data_from_context() -> None:
    provider = OpenRouterProvider.__new__(OpenRouterProvider)
    provider.provider = "openrouter"
    provider.model = "openai/gpt-4.1-mini"
    provider.base_url = "https://openrouter.ai/api/v1"
    provider.configured = True
    provider.final_url = "https://openrouter.ai/api/v1/chat/completions"

    context = {
        "intent": "marketplace",
        "marketplace": {"domains": []},
        "transfer_context": {
            "google_refresh_token": "secret",
            "calendar_event": {"summary": "Demo event", "attendees": ["a@example.com"]},
            "next_step": "Review the listing",
        },
    }

    sanitized = provider._sanitize_context(context)

    assert sanitized["intent"] == "marketplace"
    assert sanitized["marketplace"]["domains"] == []
    assert "google_refresh_token" not in sanitized["transfer_context"]
    assert "calendar_event" not in sanitized["transfer_context"]
    assert sanitized["transfer_context"]["next_step"] == "Review the listing"


def test_openrouter_service_sanitizes_google_content_in_business_idea() -> None:
    service = OpenRouterService()

    payload = service._payload(
        "Generate names for my Google Calendar event business with attendee details and OAuth token context"
    )

    user_content = payload["messages"][1]["content"]
    assert "Google Calendar event" not in user_content
    assert "attendee details" not in user_content
    assert "OAuth token" not in user_content
    assert "business idea" in user_content.lower()
