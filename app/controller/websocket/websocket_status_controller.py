from fastapi import APIRouter

from app.model.common.api_response import ApiResponse
from app.websocket.manager import (
    community_auction_connection_manager,
    notification_connection_manager,
)


router = APIRouter(
    prefix="/api/v1/ws",
    tags=["WebSocket Status"],
)


@router.get("/test", response_model=ApiResponse)
def test_websocket_module():
    return ApiResponse(
        success=True,
        message="WebSocket module is connected successfully",
        data={
            "module": "websocket",
            "status": "ready",
        },
    )


@router.get("/status", response_model=ApiResponse)
def get_websocket_status():
    return ApiResponse(
        success=True,
        message="WebSocket status fetched successfully",
        data={
            "notification_connections": notification_connection_manager.total_connections(),
            "notification_users": notification_connection_manager.active_keys(),
            "community_auction_connections": community_auction_connection_manager.total_connections(),
            "community_auction_rooms": community_auction_connection_manager.active_keys(),
        },
    )