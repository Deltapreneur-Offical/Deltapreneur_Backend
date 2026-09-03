"""Application bootstrap helpers.

These helpers keep ``app.main`` small while preserving the exact same
middleware stack and route registration order.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.api.v1 import register_person4_routes
from app.controller.addon.addon_controller import router as addon_router
from app.controller.admin.admin_controller import router as admin_router
from app.controller.admin.showcase_admin_controller import router as showcase_admin_router
from app.controller.admin.track_record_controller import (
    router as track_record_admin_router,
)
from app.controller.admin.virtual_assistant_admin_controller import (
    router as virtual_assistant_admin_router,
)
from app.controller.ai.cobrother_ai_controller import (
    compat_router as cobrother_ai_compat_router,
    router as cobrother_ai_router,
)
from app.controller.analytics.analytics_controller import router as analytics_router
from app.controller.auction.auction_controller import router as auction_router
from app.controller.auction.auction_fee_controller import router as auction_fee_router
from app.controller.auction.bidding_block_admin_controller import (
    router as bidding_block_admin_router,
)
from app.controller.auction.bid_controller import router as bid_router
from app.controller.auth.auth_controller import (
    legacy_router,
    profile_compat_router,
    router as auth_router,
)
from app.controller.becobrother.be_cobrother_controller import (
    router as becobrother_router,
)
from app.controller.cobrother.cobrother_controller import router as cobrother_router
from app.controller.cocreation.cocreation_alias_controller import (
    router as cocreation_alias_router,
)
from app.controller.cocreation.cocreation_controller import (
    router as cocreation_router,
)
from app.controller.cocreation.software_auction_controller import (
    router as software_auction_router,
)
from app.controller.community.community_auction_controller import (
    router as community_auction_router,
)
from app.controller.community.community_auction_singular_controller import (
    router as community_auction_singular_router,
)
from app.controller.community.community_controller import router as community_router
from app.controller.community.community_post_controller import (
    router as community_post_router,
)
from app.controller.community.meeting_schedule_controller import (
    router as meeting_router,
)
from app.controller.currency.currency_controller import router as currency_router
from app.controller.domain.domain_controller import router as domain_router
from app.controller.domain.domain_enquiry_controller import (
    router as domain_enquiry_router,
)
from app.controller.domain.openprovider_managed_acquisition_controller import (
    admin_router as op_managed_acquisition_admin_router,
    buyer_router as managed_acquisition_buyer_router,
)
from app.controller.domain.domain_transfer_admin_controller import (
    router as domain_transfer_admin_router,
    seller_payout_admin_router,
)
from app.controller.cocreation.technology_transfer_admin_controller import (
    router as technology_transfer_admin_router,
)
from app.controller.domain.domain_transfer_controller import (
    router as domain_transfer_router,
)
from app.controller.feedback.feedback_controller import router as feedback_router
from app.controller.fee.fee_controller import router as fee_router
from app.controller.health_router import router as health_router
from app.controller.integration_controller import router as integration_router
from app.controller.likes.like_controller import router as like_router
from app.controller.notification.notification_controller import (
    router as notification_router,
)
from app.controller.oauth_compat_controller import router as oauth_compat_router
from app.controller.operations.operations_service_admin_controller import (
    router as operations_service_admin_router,
)
from app.controller.hub_registrar_office.hub_registrar_office_controller import (
    router as hub_registrar_office_router,
)
from app.controller.hub_registrar_office.hub_registrar_office_admin_controller import (
    router as hub_registrar_office_admin_router,
)
from app.controller.hub_registrar.franchise_application_controller import (
    router as franchise_application_router,
)
from app.controller.hub_registrar.franchise_application_admin_controller import (
    router as franchise_application_admin_router,
)
from app.controller.hub_registrar.hub_registrar_category_controller import (
    router as hub_registrar_category_router,
)
from app.controller.hub_registrar.hub_registrar_category_admin_controller import (
    router as hub_registrar_category_admin_router,
)
from app.controller.operations.operations_service_controller import (
    router as operations_service_router,
)
from app.controller.operations.operations_service_request_admin_controller import (
    router as operations_service_request_admin_router,
)
from app.controller.operations.operations_service_request_controller import (
    router as operations_service_request_router,
)
from app.controller.payment.payment_controller import router as payment_router
from app.controller.payout.seller_payout_profile_controller import (
    router as seller_payout_profile_router,
)
from app.controller.public.public_controller import (
    config_router as public_config_router,
    router as public_router,
)
from app.controller.technology.technology_controller import (
    router as technology_router,
)
from app.controller.technology.technology_services_controller import (
    router as technology_services_router,
)
from app.controller.test_upload_controller import router as test_upload_router
from app.controller.user.edge_points_controller import router as edge_points_router
from app.controller.share.share_controller import router as share_router
from app.controller.venture.coventure_controller import router as coventure_router
from app.controller.venture.venture_controller import router as venture_router
from app.controller.venture.venture_deal_controller import (
    router as venture_deal_router,
)
from app.controller.cart.cart_controller import router as cart_router
from app.controller.venture.venture_pitch_controller import (
    router as venture_pitch_router,
)
from app.controller.websocket.websocket_status_controller import (
    router as websocket_status_router,
)
from app.controller.virtual_assistant.virtual_assistant_controller import (
    router as virtual_assistant_router,
)
from app.controller.virtual_assistant.virtual_assistant_workspace_controller import (
    router as virtual_assistant_workspace_router,
)
from app.core.bot_middleware import BotGuardMiddleware
from app.core.config import settings
from app.core.rate_limiter import limiter
from app.core.request_middleware import RequestContextMiddleware
from app.routes.ai_domains import (
    router as ai_domains_router,
    v1_router as ai_domains_v1_router,
)
from app.websocket.auction_socket import router as auction_ws_router
from app.websocket.community_auction_ws import (
    router as community_auction_ws_router,
)
from app.websocket.notification_socket import router as notification_socket_router
from app.websocket.sockjs_compat import router as sockjs_probe_router
from app.websocket.stomp_sockjs_compat import router as stomp_sockjs_router


def configure_middleware(app: FastAPI) -> None:
    """Register middleware in the existing order."""
    app.state.limiter = limiter

    app.add_middleware(
        SlowAPIMiddleware,
    )
    app.add_middleware(
        BotGuardMiddleware,
    )

    cors_origins = settings.resolved_cors_origins()
    cors_origin_regex = settings.resolved_cors_origin_regex()
    if cors_origins or cors_origin_regex:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_origin_regex=cors_origin_regex,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )

    # Wrap CORSMiddleware so it can log intercepted OPTIONS requests
    app.add_middleware(
        RequestContextMiddleware,
    )

    app.add_middleware(GZipMiddleware, minimum_size=1000)


def register_routers(app: FastAPI) -> None:
    """Register REST and WebSocket routers without changing public paths."""
    app.include_router(health_router)

    app.include_router(auth_router)
    app.include_router(edge_points_router)
    app.include_router(share_router)
    app.include_router(profile_compat_router)
    app.include_router(
        legacy_router,
        include_in_schema=False,
    )

    app.include_router(admin_router)
    app.include_router(showcase_admin_router)
    app.include_router(track_record_admin_router)
    app.include_router(virtual_assistant_admin_router)
    app.include_router(fee_router)
    app.include_router(analytics_router)

    app.include_router(auction_router)
    app.include_router(bid_router)
    app.include_router(auction_fee_router)
    app.include_router(bidding_block_admin_router)
    app.include_router(payment_router)

    app.include_router(ai_domains_router)
    app.include_router(ai_domains_v1_router)
    app.include_router(domain_router)
    app.include_router(domain_enquiry_router)
    app.include_router(op_managed_acquisition_admin_router)
    app.include_router(managed_acquisition_buyer_router)
    app.include_router(domain_transfer_router)
    app.include_router(domain_transfer_admin_router)
    app.include_router(technology_transfer_admin_router)
    app.include_router(hub_registrar_office_router)
    app.include_router(hub_registrar_office_admin_router)
    app.include_router(franchise_application_router)
    app.include_router(franchise_application_admin_router)
    app.include_router(hub_registrar_category_router)
    app.include_router(hub_registrar_category_admin_router)
    app.include_router(operations_service_router)
    app.include_router(operations_service_admin_router)
    app.include_router(operations_service_request_router)
    app.include_router(operations_service_request_admin_router)
    app.include_router(seller_payout_admin_router)
    app.include_router(seller_payout_profile_router)
    app.include_router(technology_router)
    app.include_router(technology_services_router)

    for creator_profile_prefix in ("/api/v1/creator", "/api/v1/community"):
        app.include_router(community_router, prefix=creator_profile_prefix)
    for creator_auction_prefix in ("/api/v1/creator-auction", "/api/v1/community-auction"):
        app.include_router(
            community_auction_singular_router,
            prefix=creator_auction_prefix,
        )
    for creator_auctions_prefix in ("/api/v1/creator-auctions", "/api/v1/community-auctions"):
        app.include_router(
            community_auction_router,
            prefix=creator_auctions_prefix,
        )
    app.include_router(community_post_router)
    app.include_router(meeting_router)

    app.include_router(cart_router)
    app.include_router(currency_router)
    app.include_router(addon_router)

    app.include_router(notification_router)
    app.include_router(like_router)

    app.include_router(venture_router)
    app.include_router(venture_pitch_router)
    app.include_router(venture_deal_router)
    app.include_router(coventure_router)

    app.include_router(software_auction_router)
    for technology_prefix in ("/api/v1/technology", "/api/v1/cocreation"):
        app.include_router(cocreation_alias_router, prefix=technology_prefix)
        app.include_router(cocreation_router, prefix=technology_prefix)

    app.include_router(cobrother_router)
    app.include_router(becobrother_router)
    app.include_router(cobrother_ai_router)
    app.include_router(cobrother_ai_compat_router)

    app.include_router(public_router)
    app.include_router(public_config_router)
    app.include_router(feedback_router)
    app.include_router(virtual_assistant_router)
    app.include_router(virtual_assistant_workspace_router)
    app.include_router(integration_router)
    app.include_router(oauth_compat_router)

    if settings.ENVIRONMENT == "development":
        app.include_router(test_upload_router)

    register_person4_routes(app)

    app.include_router(auction_ws_router)
    app.include_router(stomp_sockjs_router)
    app.include_router(sockjs_probe_router)
    app.include_router(community_auction_ws_router)
    app.include_router(notification_socket_router)
    app.include_router(websocket_status_router)
