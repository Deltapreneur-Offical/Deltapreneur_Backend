from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controller.admin.fee_controller import (
    compat_router as fee_compat_router,
    get_fee_service,
)
from app.controller.domain import domain_controller
from app.controller.venture import venture_controller
from app.core.exceptions import register_exception_handlers
from app.core.dependencies import get_current_user
from app.entity.user.app_user import AppUser
from app.entity.user.user_role import UserRole


class _VentureServiceStub:
    async def update_venture_image(self, venture_id, image_url, *, actor):  # noqa: ANN001
        class _Obj:
            id = venture_id

        _ = (image_url, actor)
        return _Obj()


class _MarketplaceServiceStub:
    async def update_listing_logo(self, listing_id, logo_url, *, actor):  # noqa: ANN001
        class _Obj:
            id = listing_id

        _ = (logo_url, actor)
        return _Obj()


def _fake_user() -> AppUser:
    return AppUser(
        id=uuid.uuid4(),
        email="compat@test.local",
        firstname="Compat",
        lastname="User",
        role=UserRole.USER,
        active=True,
        email_verified=True,
        profile_complete=True,
    )


class _FeeServiceStub:
    async def list_my_requests(self, user):  # noqa: ANN001
        _ = user
        return {"requests": [{"id": "req-1"}]}

    async def create_order(self, request_id, user):  # noqa: ANN001
        _ = user
        return {"success": True, "requestId": request_id, "orderId": "order_123"}

    async def verify(self, request_id, user, **kwargs):  # noqa: ANN001
        _ = (user, kwargs)
        return {"success": True, "requestId": request_id, "paid": True}

    async def cancel(self, request_id, user):  # noqa: ANN001
        _ = user
        return {"success": True, "requestId": request_id, "status": "FAILED"}


def test_fee_compat_routes_are_available():
    app = FastAPI()
    app.include_router(fee_compat_router)
    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[get_fee_service] = _FeeServiceStub
    client = TestClient(app)

    res = client.get("/api/v1/fee/my-requests")
    assert res.status_code == 200
    assert "requests" in res.json()

    res = client.post("/api/v1/fee/requests/test-id/create-order")
    assert res.status_code == 200
    assert "success" in res.json()

    res = client.post(
        "/api/v1/fee/requests/test-id/verify",
        json={
            "razorpayPaymentId": "pay_test",
            "razorpayOrderId": "order_test",
            "razorpaySignature": "sig_test",
        },
    )
    assert res.status_code == 200
    assert "success" in res.json()

    res = client.post("/api/v1/fee/requests/test-id/cancel")
    assert res.status_code == 200
    assert res.json()["success"] is True


def test_fee_compat_routes_require_auth_without_override():
    app = FastAPI()
    app.include_router(fee_compat_router)
    app.dependency_overrides[get_fee_service] = _FeeServiceStub
    client = TestClient(app)

    res = client.get("/api/v1/fee/my-requests")
    assert res.status_code == 401

    res = client.post("/api/v1/fee/requests/test-id/create-order")
    assert res.status_code == 401


def test_fee_compat_calls_real_shapes():
    app = FastAPI()
    app.include_router(fee_compat_router)
    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[get_fee_service] = _FeeServiceStub
    client = TestClient(app)

    create_res = client.post("/api/v1/fee/requests/abc/create-order")
    verify_res = client.post(
        "/api/v1/fee/requests/abc/verify",
        json={
            "razorpayPaymentId": "pay_test",
            "razorpayOrderId": "order_test",
            "razorpaySignature": "sig_test",
        },
    )
    cancel_res = client.post("/api/v1/fee/requests/abc/cancel")

    assert create_res.status_code == 200
    assert create_res.json()["success"] is True
    assert create_res.json()["orderId"] == "order_123"

    assert verify_res.status_code == 200
    assert verify_res.json()["success"] is True
    assert verify_res.json()["paid"] is True

    assert cancel_res.status_code == 200
    assert cancel_res.json()["success"] is True


def test_venture_image_upload_route_exists(monkeypatch):
    app = FastAPI()
    app.include_router(venture_controller.router)
    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[venture_controller.get_venture_service] = _VentureServiceStub
    async def _upload_image_stub(**_kwargs):
        return "https://cdn.test/v.png"

    monkeypatch.setattr(venture_controller, "upload_image", _upload_image_stub)
    client = TestClient(app)

    venture_id = uuid.uuid4()
    res = client.post(
        f"/api/v1/venture/{venture_id}/image",
        files={"file": ("v.png", b"fake", "image/png")},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["ventureId"] == str(venture_id)
    assert body["imageUrl"].startswith("https://")


def test_domain_image_upload_route_exists(monkeypatch):
    app = FastAPI()
    app.include_router(domain_controller.router)
    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[domain_controller.get_marketplace_service] = _MarketplaceServiceStub
    async def _upload_image_stub(**_kwargs):
        return "https://cdn.test/d.png"

    monkeypatch.setattr(domain_controller, "upload_image", _upload_image_stub)
    client = TestClient(app)

    listing_id = uuid.uuid4()
    res = client.post(
        f"/api/v1/domain/{listing_id}/image",
        files={"file": ("d.png", b"fake", "image/png")},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["listingId"] == str(listing_id)
    assert body["imageUrl"].startswith("https://")


def test_venture_image_upload_propagates_forbidden(monkeypatch):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(venture_controller.router)
    app.dependency_overrides[get_current_user] = _fake_user

    class _ForbiddenServiceStub:
        async def update_venture_image(self, venture_id, image_url, *, actor):  # noqa: ANN001
            from app.core.exceptions import AppException

            _ = (venture_id, image_url, actor)
            raise AppException("You are not authorized to edit this venture.", status_code=403)

    app.dependency_overrides[venture_controller.get_venture_service] = _ForbiddenServiceStub

    async def _upload_image_stub(**_kwargs):
        return "https://cdn.test/v.png"

    monkeypatch.setattr(venture_controller, "upload_image", _upload_image_stub)
    client = TestClient(app)

    venture_id = uuid.uuid4()
    res = client.post(
        f"/api/v1/venture/{venture_id}/image",
        files={"file": ("v.png", b"fake", "image/png")},
    )

    assert res.status_code == 403


def test_domain_image_upload_propagates_forbidden(monkeypatch):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(domain_controller.router)
    app.dependency_overrides[get_current_user] = _fake_user

    class _ForbiddenServiceStub:
        async def update_listing_logo(self, listing_id, logo_url, *, actor):  # noqa: ANN001
            from app.core.exceptions import AppException

            _ = (listing_id, logo_url, actor)
            raise AppException("Not authorized to edit this listing.", status_code=403)

    app.dependency_overrides[domain_controller.get_marketplace_service] = _ForbiddenServiceStub

    async def _upload_image_stub(**_kwargs):
        return "https://cdn.test/d.png"

    monkeypatch.setattr(domain_controller, "upload_image", _upload_image_stub)
    client = TestClient(app)

    listing_id = uuid.uuid4()
    res = client.post(
        f"/api/v1/domain/{listing_id}/image",
        files={"file": ("d.png", b"fake", "image/png")},
    )

    assert res.status_code == 403
