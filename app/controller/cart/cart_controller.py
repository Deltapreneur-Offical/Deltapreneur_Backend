"""Shopping cart REST controller."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.entity.user.app_user import AppUser
from app.schemas.cart_schemas import (
    AddToCartRequest,
    CartCancelCheckoutRequest,
    CartCheckoutRequest,
    CartVerifyRequest,
    OpenProviderManagedConfirmRequest,
    PremiumMarketplaceConfirmRequest,
    UpdateCartItemRequest,
    UpdateDomainRegistrationPeriodRequest,
)
from app.service.cart.cart_checkout_service import CartCheckoutService
from app.service.cart.cart_service import CartService
from app.service.cart.openprovider_managed_cart_service import (
    OpenProviderManagedCartService,
)
from app.service.cart.premium_marketplace_cart_service import PremiumMarketplaceCartService

router = APIRouter(prefix="/api/v1/cart", tags=["Cart"])


async def _cart_service(db: AsyncSession = Depends(get_async_db)) -> CartService:
    return CartService(db)


async def _checkout_service(db: AsyncSession = Depends(get_async_db)) -> CartCheckoutService:
    return CartCheckoutService(db)


async def _premium_marketplace_cart_service(
    db: AsyncSession = Depends(get_async_db),
) -> PremiumMarketplaceCartService:
    return PremiumMarketplaceCartService(db)


async def _op_managed_cart_service(
    db: AsyncSession = Depends(get_async_db),
) -> OpenProviderManagedCartService:
    return OpenProviderManagedCartService(db)


@router.get("")
async def get_cart(
    service: CartService = Depends(_cart_service),
    current_user: AppUser = Depends(get_current_user),
):
    cart = await service.get_cart(current_user.id)
    return cart.model_dump(by_alias=True)


@router.get("/count")
async def get_cart_count(
    service: CartService = Depends(_cart_service),
    current_user: AppUser = Depends(get_current_user),
):
    count = await service.get_item_count(current_user.id)
    return {"count": count}


@router.post("/items")
async def add_to_cart(
    body: AddToCartRequest,
    service: CartService = Depends(_cart_service),
    current_user: AppUser = Depends(get_current_user),
):
    item = await service.add_item(current_user.id, body)
    await service._session.commit()
    return {"success": True, "item": item.model_dump(by_alias=True)}


@router.patch("/items/{item_id}")
async def update_cart_item(
    item_id: uuid.UUID,
    body: UpdateCartItemRequest,
    service: CartService = Depends(_cart_service),
    current_user: AppUser = Depends(get_current_user),
):
    item = await service.update_item(item_id, current_user.id, body)
    await service._session.commit()
    return {"success": True, "item": item.model_dump(by_alias=True)}


@router.delete("/items/{item_id}")
async def remove_cart_item(
    item_id: uuid.UUID,
    service: CartService = Depends(_cart_service),
    current_user: AppUser = Depends(get_current_user),
):
    await service.remove_item(item_id, current_user.id)
    return {"success": True, "message": "Item removed from cart."}


@router.delete("")
async def clear_cart(
    service: CartService = Depends(_cart_service),
    current_user: AppUser = Depends(get_current_user),
):
    count = await service.clear_cart(current_user.id)
    return {"success": True, "message": f"Removed {count} item(s) from cart."}


@router.patch("/domain-registration-period")
async def update_domain_registration_period(
    body: UpdateDomainRegistrationPeriodRequest,
    service: CartService = Depends(_cart_service),
    current_user: AppUser = Depends(get_current_user),
):
    cart = await service.update_domain_registration_period(
        current_user.id,
        body.period_years,
        item_id=body.item_id,
    )
    await service._session.commit()
    return cart.model_dump(by_alias=True)


@router.post("/premium-marketplace/confirm")
async def confirm_premium_marketplace(
    body: PremiumMarketplaceConfirmRequest,
    service: PremiumMarketplaceCartService = Depends(_premium_marketplace_cart_service),
    current_user: AppUser = Depends(get_current_user),
):
    """No-payment confirmation for marketplace domains above ₹5L."""
    return await service.confirm(
        current_user,
        full_name=body.full_name,
        email=body.email,
        phone=body.phone,
        message=body.message,
        listing_id=body.listing_id,
    )


@router.post("/openprovider-managed/confirm")
async def confirm_openprovider_managed(
    body: OpenProviderManagedConfirmRequest,
    service: OpenProviderManagedCartService = Depends(_op_managed_cart_service),
    current_user: AppUser = Depends(get_current_user),
):
    """No-payment confirmation for OpenProvider registrations above ₹5L payable."""
    return await service.confirm(
        current_user,
        full_name=body.full_name,
        email=body.email,
        phone=body.phone,
        message=body.message,
        item_id=body.item_id,
    )


@router.post("/checkout")
async def checkout(
    body: CartCheckoutRequest,
    service: CartCheckoutService = Depends(_checkout_service),
    current_user: AppUser = Depends(get_current_user),
):
    result = await service.create_checkout_order(
        current_user,
        redeem_points=body.redeem_points,
        currency=body.currency,
        buyer_name=body.buyer_name or "",
        buyer_email=body.buyer_email or "",
        buyer_phone=body.buyer_phone or "",
        registrant=body.registrant,
        period_years=body.period_years,
    )
    return result


@router.post("/checkout/verify")
async def verify_checkout(
    body: CartVerifyRequest,
    service: CartCheckoutService = Depends(_checkout_service),
    current_user: AppUser = Depends(get_current_user),
):
    result = await service.verify_checkout_payment(current_user, body)
    return result


@router.post("/checkout/cancel")
async def cancel_checkout(
    body: CartCancelCheckoutRequest,
    service: CartCheckoutService = Depends(_checkout_service),
    current_user: AppUser = Depends(get_current_user),
):
    result = await service.cancel_checkout_order(current_user, body.razorpay_order_id)
    return result
