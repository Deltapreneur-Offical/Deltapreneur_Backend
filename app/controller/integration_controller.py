"""Public integration map for frontend ↔ Python backend connectivity."""

from fastapi import APIRouter

from app.core.config import settings
from app.model.common.api_response import ApiResponse

router = APIRouter(prefix="/api/v1/integration", tags=["Integration"])


def _module(
    name: str,
    status: str,
    frontend_group: str,
    backend_prefix: str,
    notes: str = "",
) -> dict:
    return {
        "name": name,
        "status": status,
        "frontendApi": frontend_group,
        "backendPrefix": backend_prefix,
        "notes": notes,
    }


@router.get("/status", response_model=ApiResponse)
def integration_status():
    connected = [
        _module("Auth", "connected", "authAPI", "/api/v1/auth"),
        _module("Profile", "connected", "profileAPI", "/api/v1/auth/me"),
        _module("Ventures", "connected", "ventureAPI", "/api/v1/venture"),
        _module("Venture pitches & deals", "connected", "venturePitchAPI / ventureDealAPI", "/api/v1/venture-pitches, /api/v1/venture-deals"),
        _module("Co-venture", "connected", "coVentureAPI", "/api/v1/coventure"),
        _module("Creator", "connected", "creatorAPI", "/api/v1/creator"),
        _module("Technology / cocreation", "connected", "technologyAPI", "/api/v1/technology (+ /api/v1/cocreation alias)"),
        _module("Domain marketplace", "connected", "domainAPI", "/api/v1/domain"),
        _module("Domain storefront", "connected", "domainStorefrontAPI", "/api/v1/domain/storefront"),
        _module("Domain transfers", "connected", "domainTransferAPI", "/api/v1/domain/transfers"),
        _module("Auctions", "connected", "auctionAPI", "/api/v1/auction"),
        _module("Likes", "connected", "likeAPI", "/api/v1/likes"),
        _module("Notifications", "connected", "notificationAPI", "/api/v1/notifications"),
        _module("Admin", "connected", "adminAPI", "/api/v1/admin"),
        _module("Fees", "connected", "feeAPI", "/api/v1/fee"),
        _module("CoBrother ops", "connected", "coBrotherAPI", "/api/v1/cobrother"),
        _module("Feedback", "connected", "feedbackAPI", "/api/v1/feedback"),
        _module("Join us", "connected", "joinUsAPI", "/api/v1/becobrother"),
        _module("WebSocket (notifications)", "connected", "useNotificationSocket", "/ws/notifications/{user_id}"),
        _module("WebSocket (domain auction)", "connected", "useAuction", "/ws/auction/{id}"),
    ]

    partial = [
        _module(
            "Creator posts",
            "partial",
            "(no frontend page)",
            "/api/v1/community-posts",
            "Backend ready; no UI wired yet",
        ),
        _module(
            "Direct user messaging",
            "partial",
            "(not implemented)",
            "—",
            "Use domain enquiry, meetings, and notifications instead",
        ),
    ]

    return ApiResponse(
        success=True,
        message="Frontend ↔ backend integration map",
        data={
            "backend": "HubRegistrar Python (FastAPI)",
            "environment": settings.ENVIRONMENT,
            "connectedCount": len(connected),
            "partialCount": len(partial),
            "connected": connected,
            "partial": partial,
            "verificationFlags": {
                "backendRequireDomainVerification": settings.REQUIRE_DOMAIN_VERIFICATION_BEFORE_PURCHASE,
                "backendRequireTechnologyVerification": settings.REQUIRE_TECHNOLOGY_VERIFICATION_BEFORE_PURCHASE,
                "frontendEnvKeys": [
                    "VITE_REQUIRE_DOMAIN_VERIFICATION_BEFORE_PURCHASE",
                    "VITE_REQUIRE_TECHNOLOGY_VERIFICATION_BEFORE_PURCHASE",
                ],
            },
            "quickStart": {
                "backend": "cd cobrother_backend && uvicorn app.main:app --reload --port 8000",
                "frontend": "cd CoBrother_Frontend && npm run dev",
                "env": "VITE_API_URL=http://127.0.0.1:8000/api",
            },
        },
    )
