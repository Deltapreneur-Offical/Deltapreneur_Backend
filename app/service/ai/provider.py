# COMPLIANCE NOTE: To adhere to Google API Services User Data Policy (Limited Use), 
# DO NOT import or inject any raw or derived user data from Google Calendar or 
# Google Meet APIs into this AI/OpenRouter payload context.

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

OPENROUTER_CHAT_COMPLETIONS_PATH = "/chat/completions"
EXPECTED_OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_PROVIDER = "openrouter"
OPENAI_PROVIDER = "openai"
OPENROUTER_MODEL = "openai/gpt-4.1-mini"
OPENAI_MODEL = "gpt-4.1-mini"
OPENROUTER_MAX_TOKENS = 1024
TEMPORARY_UNAVAILABLE_MESSAGE = "AI service temporarily unavailable. Please try again."
GOOGLE_DATA_REDACTION_MESSAGE = "[redacted: Google API data omitted]"
GOOGLE_DATA_PATTERNS = (
    "google",
    "calendar",
    "meet",
    "oauth",
    "token",
    "attendee",
    "attendees",
    "conference",
    "refresh_token",
    "access_token",
    "id_token",
    "oauth2",
    "googleapis",
    "gmail",
    "drive",
    "calendar.v3",
)


class OpenRouterProviderError(Exception):
    def __init__(
        self,
        *,
        model: str,
        url: str,
        status_code: int | None,
        message: str,
        response_body: str | None = None,
    ) -> None:
        self.model = model
        self.url = url
        self.status_code = status_code
        self.response_body = response_body
        detail = f"url={url} model={model}"
        if status_code is not None:
            detail += f" status={status_code}"
        detail += f" message={message}"
        if response_body:
            detail += f" response_body={response_body[:4000]}"
        super().__init__(detail)


def _redacted_headers(headers: dict[str, str]) -> dict[str, str]:
    redacted = dict(headers)
    if "Authorization" in redacted:
        redacted["Authorization"] = "Bearer <redacted>"
    return redacted


class OpenRouterProvider:
    def __init__(self) -> None:
        self.provider = (
            settings.CHAT_AI_PROVIDER
            or settings.AI_PROVIDER
            or OPENROUTER_PROVIDER
        ).strip().lower()
        if self.provider not in {OPENROUTER_PROVIDER, OPENAI_PROVIDER}:
            logger.warning("Unsupported CHAT_AI_PROVIDER=%s; using OpenRouter.", self.provider)
            self.provider = OPENROUTER_PROVIDER

        if self.provider == OPENAI_PROVIDER:
            self.model = (settings.AI_MODEL or OPENAI_MODEL).strip()
            self.base_url = settings.OPENAI_BASE_URL.strip().rstrip("/")
            self.configured = bool(settings.OPENAI_API_KEY.strip())
        else:
            self.model = (settings.AI_MODEL or settings.OPENROUTER_MODEL or OPENROUTER_MODEL).strip()
            self.base_url = settings.OPENROUTER_BASE_URL.strip().rstrip("/")
            self.configured = bool(settings.OPENROUTER_API_KEY.strip())

        self.final_url = self.base_url + OPENROUTER_CHAT_COMPLETIONS_PATH
        logger.info(
            "Chat AI provider initialized configured=%s provider=%s base_url=%s final_url=%s selected_model=%s site_url=%s app_name=%s",
            self.configured,
            self.provider,
            self.base_url,
            self.final_url,
            self.model,
            settings.OPENROUTER_SITE_URL,
            settings.OPENROUTER_APP_NAME,
        )

    async def stream_chat(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        context: dict[str, Any],
    ) -> AsyncIterator[str]:
        if not self.configured:
            logger.error("%s API key is missing; AI service unavailable.", self.provider)
            yield TEMPORARY_UNAVAILABLE_MESSAGE
            return

        try:
            async for token in self._stream_single_model(
                system_prompt=system_prompt,
                messages=messages,
                context=context,
            ):
                yield token
        except OpenRouterProviderError as exc:
            logger.exception(
                "Chat AI request failed provider=%s final_url=%s selected_model=%s error=%s",
                self.provider,
                self.final_url,
                self.model,
                exc,
            )
            yield TEMPORARY_UNAVAILABLE_MESSAGE

    def _sanitize_text(self, value: str | None) -> str:
        if not value:
            return ""
        lower = value.lower()
        if any(pattern in lower for pattern in GOOGLE_DATA_PATTERNS):
            return GOOGLE_DATA_REDACTION_MESSAGE
        return value

    def _sanitize_context(self, value: Any) -> Any:
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                key_lower = str(key).lower()
                if any(pattern in key_lower for pattern in GOOGLE_DATA_PATTERNS):
                    continue
                sanitized[key] = self._sanitize_context(item)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize_context(item) for item in value]
        if isinstance(value, str):
            return self._sanitize_text(value)
        return value

    async def _stream_single_model(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        context: dict[str, Any],
    ) -> AsyncIterator[str]:
        if self.provider == OPENROUTER_PROVIDER and self.final_url != EXPECTED_OPENROUTER_CHAT_URL:
            raise OpenRouterProviderError(
                model=self.model,
                url=self.final_url,
                status_code=None,
                message=(
                    "Invalid OpenRouter URL. Expected "
                    f"{EXPECTED_OPENROUTER_CHAT_URL}, got {self.final_url}"
                ),
            )

        sanitized_system_prompt = self._sanitize_text(system_prompt)
        sanitized_context = self._sanitize_context(context)
        sanitized_messages = []
        for message in messages[-12:]:
            if isinstance(message, dict):
                sanitized_message = dict(message)
                if "content" in sanitized_message:
                    sanitized_message["content"] = self._sanitize_text(sanitized_message.get("content"))
                sanitized_messages.append(sanitized_message)
            else:
                sanitized_messages.append(message)

        payload = {
            "model": self.model,
            "stream": True,
            "temperature": 0.45,
            "max_tokens": OPENROUTER_MAX_TOKENS,
            "messages": [
                {"role": "system", "content": sanitized_system_prompt},
                {
                    "role": "system",
                    "content": "Marketplace context JSON:\n" + json.dumps(sanitized_context, default=str)[:18000],
                },
                *sanitized_messages,
            ],
        }
        if self.provider == OPENAI_PROVIDER:
            headers = {
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            }
        else:
            headers = {
                "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                "HTTP-Referer": settings.OPENROUTER_SITE_URL,
                "X-Title": settings.OPENROUTER_APP_NAME,
            }

        try:
            timeout = httpx.Timeout(float(settings.AI_REQUEST_TIMEOUT_SECONDS), connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                logger.info(
                    "Chat AI final request provider=%s final_url=%s selected_model=%s headers=%s max_tokens=%s message_count=%s context_intent=%s marketplace_unavailable=%s",
                    self.provider,
                    self.final_url,
                    self.model,
                    _redacted_headers(headers),
                    OPENROUTER_MAX_TOKENS,
                    len(payload["messages"]),
                    context.get("intent"),
                    context.get("marketplace_unavailable"),
                )
                # Exact failure point for DNS/connectivity errors such as getaddrinfo failed.
                async with client.stream("POST", self.final_url, headers=headers, json=payload) as response:
                    logger.info(
                        "Chat AI response status=%s provider=%s final_url=%s selected_model=%s headers=%s",
                        response.status_code,
                        self.provider,
                        self.final_url,
                        self.model,
                        _redacted_headers(headers),
                    )
                    if response.status_code >= 400:
                        body = (await response.aread()).decode(errors="replace")
                        raise OpenRouterProviderError(
                            model=self.model,
                            url=self.final_url,
                            status_code=response.status_code,
                            message=response.reason_phrase,
                            response_body=body,
                        )
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line.removeprefix("data:").strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        token = (
                            chunk.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content")
                        )
                        if token:
                            yield token
        except OpenRouterProviderError:
            raise
        except Exception as exc:
            raise OpenRouterProviderError(
                model=self.model,
                url=self.final_url,
                status_code=None,
                message=f"{exc.__class__.__name__}: {exc}",
            ) from exc
