"""Domain registration storefront REST controller."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.entity.user.app_user import AppUser
from app.service.domain.domain_registration_service import DomainRegistrationService

router = APIRouter(prefix="/api/v1/domain/storefront", tags=["Domain Storefront"])
logger = logging.getLogger(__name__)


async def get_registration_service(
    db: AsyncSession = Depends(get_async_db),
) -> DomainRegistrationService:
    return DomainRegistrationService(db)


@router.get("/config")
async def storefront_config(
    service: DomainRegistrationService = Depends(get_registration_service),
) -> dict:
    return service.storefront_config()


@router.get("/prices")
async def storefront_prices(
    service: DomainRegistrationService = Depends(get_registration_service),
) -> dict:
    return await service.get_service_prices()


@router.post("/order")
async def create_registration_order(
    body: dict,
    redeem_points: bool = False,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.create_order(body, buyer=current_user, redeem_points=redeem_points)


@router.post("/order/verify")
async def verify_registration_order(
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.verify_and_provision(body, buyer=current_user)


@router.get("/orders")
async def list_my_registration_orders(
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> list:
    orders = await service.list_my_orders(current_user)
    logger.info(
        "purchases.summary.domain_registration user=%s count=%s items=%s",
        current_user.id,
        len(orders),
        [{"id": str(x.get("id")), "domain": x.get("domain"), "status": x.get("status"), "lifecycleStatus": x.get("lifecycleStatus"), "razorpayPaymentId": x.get("razorpayPaymentId") or x.get("razorpay_payment_id")} for x in orders],
    )
    return orders


@router.get("/orders/{order_id}")
async def get_registration_order(
    order_id: uuid.UUID,
    sync: bool = Query(True, description="Sync status from registrar when configured"),
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.get_order_detail(order_id, buyer=current_user, sync=sync)


@router.post("/orders/{order_id}/sync")
async def sync_registration_order(
    order_id: uuid.UUID,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.sync_order(order_id, buyer=current_user)


@router.post("/orders/{order_id}/resend-verification")
async def resend_registration_verification(
    order_id: uuid.UUID,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.resend_verification(order_id, buyer=current_user)


@router.post("/orders/{order_id}/retry")
async def retry_provision(
    order_id: uuid.UUID,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.retry_provision(order_id, buyer=current_user)


@router.post("/orders/{order_id}/nameservers")
async def update_domain_nameservers(
    order_id: uuid.UUID,
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    nameservers = body.get("nameservers", [])
    if not isinstance(nameservers, list):
        raise ValueError("nameservers must be a list of strings")
    return await service.update_nameservers(order_id, nameservers, buyer=current_user)


@router.post("/orders/{order_id}/renew")
async def renew_domain(
    order_id: uuid.UUID,
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    period = int(body.get("period", 1))
    return await service.renew_domain_direct(order_id, period, buyer=current_user)


@router.post("/orders/{order_id}/renew/payment")
async def create_renewal_payment(
    order_id: uuid.UUID,
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    period = int(body.get("period", 1))
    return await service.create_renewal_payment_order(order_id, period, buyer=current_user)


@router.get("/orders/{order_id}/renew/quote")
async def renewal_quote(
    order_id: uuid.UUID,
    period: int = Query(1, ge=1, le=10),
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.get_renewal_quote(order_id, period, buyer=current_user)


@router.post("/orders/{order_id}/renew/payment/verify")
async def verify_renewal_payment(
    order_id: uuid.UUID,
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.verify_renewal_payment(order_id, body, buyer=current_user)


@router.post("/transfer/quote")
async def transfer_quote(
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    domain = str(body.get("domain", "")).strip()
    if not domain:
        raise ValueError("domain is required")
    return await service.get_transfer_quote(domain)


@router.post("/transfer/payment")
async def create_transfer_payment(
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.create_transfer_payment_order(body, buyer=current_user)


@router.post("/transfer/payment/verify")
async def verify_transfer_payment(
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.verify_transfer_payment(body, buyer=current_user)


@router.post("/orders/{order_id}/transfer/payment/retry")
async def retry_transfer_payment(
    order_id: uuid.UUID,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.retry_transfer_payment(order_id, buyer=current_user)


@router.post("/transfer")
async def initiate_domain_transfer(
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.initiate_transfer(body, buyer=current_user)


@router.post("/orders/{order_id}/addons/email/payment")
async def create_email_addon_payment(
    order_id: uuid.UUID,
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.create_email_addon_payment_order(order_id, body, buyer=current_user)


@router.post("/orders/{order_id}/addons/email/payment/verify")
async def verify_email_addon_payment(
    order_id: uuid.UUID,
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.verify_email_addon_payment(order_id, body, buyer=current_user)


@router.post("/orders/{order_id}/addons/email")
async def add_email_addon(
    order_id: uuid.UUID,
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    from app.core.exceptions import AppException

    raw = body.get("mailbox", "")
    if isinstance(raw, dict):
        mailbox = str(raw.get("email") or raw.get("mailbox") or raw.get("prefix") or "").strip()
    else:
        mailbox = str(raw or "").strip()
    if not mailbox:
        raise AppException("mailbox prefix is required", status_code=400)
    return await service.add_email_addon(order_id, mailbox, buyer=current_user)


@router.post("/orders/{order_id}/addons/ssl/payment")
async def create_ssl_addon_payment(
    order_id: uuid.UUID,
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.create_ssl_addon_payment_order(order_id, body, buyer=current_user)


@router.post("/orders/{order_id}/addons/ssl/payment/verify")
async def verify_ssl_addon_payment(
    order_id: uuid.UUID,
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.verify_ssl_addon_payment(order_id, body, buyer=current_user)


@router.post("/orders/{order_id}/addons/ssl")
async def add_ssl_addon(
    order_id: uuid.UUID,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.add_ssl_addon(order_id, buyer=current_user)


@router.post("/orders/{order_id}/addons/restore/payment")
async def create_restore_addon_payment(
    order_id: uuid.UUID,
    body: dict | None = None,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.create_restore_addon_payment_order(
        order_id, body or {}, buyer=current_user
    )


@router.post("/orders/{order_id}/addons/restore/payment/verify")
async def verify_restore_addon_payment(
    order_id: uuid.UUID,
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.verify_restore_addon_payment(order_id, body, buyer=current_user)


@router.post("/orders/{order_id}/addons/easydmarc/payment")
async def create_easydmarc_addon_payment(
    order_id: uuid.UUID,
    body: dict | None = None,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.create_easydmarc_addon_payment_order(
        order_id, body or {}, buyer=current_user
    )


@router.post("/orders/{order_id}/addons/easydmarc/payment/verify")
async def verify_easydmarc_addon_payment(
    order_id: uuid.UUID,
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.verify_easydmarc_addon_payment(order_id, body, buyer=current_user)


@router.post("/orders/{order_id}/addons/spamexperts/payment")
async def create_spamexperts_addon_payment(
    order_id: uuid.UUID,
    body: dict | None = None,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.create_spamexperts_addon_payment_order(
        order_id, body or {}, buyer=current_user
    )


@router.post("/orders/{order_id}/addons/spamexperts/payment/verify")
async def verify_spamexperts_addon_payment(
    order_id: uuid.UUID,
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return await service.verify_spamexperts_addon_payment(order_id, body, buyer=current_user)


@router.post("/transfer/out")
async def initiate_domain_transfer_out(
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    domain = str(body.get("domain", "")).strip()
    if not domain:
        raise ValueError("domain name is required")
    return await service.retrieve_auth_code_and_unlock(domain, buyer=current_user)


@router.get("/orders/{order_id}/dns/records")
async def get_dns_records(
    order_id: uuid.UUID,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> list:
    return await service.get_dns_records(order_id, buyer=current_user)


@router.post("/orders/{order_id}/dns/records")
async def create_dns_record(
    order_id: uuid.UUID,
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    await service.create_dns_record(order_id, body, buyer=current_user)
    return {"success": True}


@router.delete("/orders/{order_id}/dns/records/{record_id}")
async def delete_dns_record(
    order_id: uuid.UUID,
    record_id: str,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    await service.delete_dns_record(order_id, record_id, buyer=current_user)
    return {"success": True}


@router.put("/orders/{order_id}/dns/records/{record_id}")
async def update_dns_record(
    order_id: uuid.UUID,
    record_id: str,
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    await service.update_dns_record(order_id, record_id, body, buyer=current_user)
    return {"success": True}


@router.post("/orders/{order_id}/dnssec")
async def toggle_dnssec(
    order_id: uuid.UUID,
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    enabled = bool(body.get("enabled", False))
    return await service.toggle_dnssec(order_id, enabled, buyer=current_user)


@router.post("/orders/{order_id}/addons/email/password")
async def update_mailbox_password(
    order_id: uuid.UUID,
    body: dict,
    service: DomainRegistrationService = Depends(get_registration_service),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    mailbox = str(body.get("mailbox", "")).strip()
    password = str(body.get("password", "")).strip()
    if not mailbox or not password:
        raise ValueError("mailbox and password are required")
    return await service.update_mailbox_password(order_id, mailbox, password, buyer=current_user)




