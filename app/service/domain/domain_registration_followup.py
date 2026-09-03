"""Post-payment sync, notifications, and enriched order responses."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

# pyrefly: ignore [missing-import]
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
from app.entity.user.app_user import AppUser
from app.repository.domain_registration_order_repository import (
    DomainRegistrationOrderRepository,
)
from app.service.auth.mail_service import MailService
from app.utils.domain_gst import order_gst_payload
from app.utils.registration_enums import RegistrationOrderStatus
from app.utils.registration_lifecycle import registration_lifecycle_status

logger = logging.getLogger(__name__)

_PENDING_SINCE_PREFIX = "PENDING_SINCE:"
_RACEY_FAILURE_MARKERS = (
    "domain no longer available at registrar",
)


def should_send_registration_failed_email(order: DomainRegistrationOrder) -> bool:
    """True only for a genuine terminal failure — not in-flight / recoverable races."""
    if order.status != RegistrationOrderStatus.PROVISION_FAILED:
        return False
    if order.email_failed_sent:
        return False
    if order.email_active_sent:
        return False
    if registration_lifecycle_status(order) != "registration_failed":
        return False
    message = (order.provision_message or "").strip().lower()
    if any(marker in message for marker in _RACEY_FAILURE_MARKERS):
        return False
    return True


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def stamp_registration_pending_since(order: DomainRegistrationOrder) -> None:
    """Record when REGISTRATION_PENDING began (survives reconcile updated_at bumps)."""
    msg = order.provision_message or ""
    if msg.startswith(_PENDING_SINCE_PREFIX):
        return
    stamp = _utc_now().isoformat()
    rest = msg.strip()
    order.provision_message = (
        f"{_PENDING_SINCE_PREFIX}{stamp}|{rest}" if rest else f"{_PENDING_SINCE_PREFIX}{stamp}"
    )


def pending_since_of(order: DomainRegistrationOrder) -> datetime | None:
    """Parse PENDING_SINCE stamp; fall back to created_at for legacy rows."""
    msg = order.provision_message or ""
    if msg.startswith(_PENDING_SINCE_PREFIX):
        raw = msg[len(_PENDING_SINCE_PREFIX) :].split("|", 1)[0].strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return _as_utc(parsed)
        except ValueError:
            pass
    return _as_utc(order.created_at)


def _order_detail_url(order_id: uuid.UUID) -> str:
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    return f"{base}/storefront/orders/{order_id}"


def _order_dns_url(order_id: uuid.UUID) -> str:
    """Customer-facing HubRegistrar DNS management URL (order page DNS tab)."""
    return f"{_order_detail_url(order_id)}#dns"


HUBREGISTRAR_STOREFRONT_ORIGIN = "https://hubregistrar.com"


def hubregistrar_order_detail_url(order_id: uuid.UUID) -> str:
    """Storefront order page on hubregistrar.com (registration-success email only)."""
    return f"{HUBREGISTRAR_STOREFRONT_ORIGIN}/storefront/orders/{order_id}"


def hubregistrar_order_dns_url(order_id: uuid.UUID) -> str:
    """DNS tab on the HubRegistrar order page (registration-success email only)."""
    return f"{hubregistrar_order_detail_url(order_id)}#dns"


def _normalize_icann_status(raw: str | None) -> str:
    if not raw:
        return "UNKNOWN"
    upper = str(raw).strip().upper()
    if upper in ("VERIFIED", "PENDING", "SUSPENDED", "UNKNOWN"):
        return upper
    return "UNKNOWN"


def _parse_order_nameservers(order: DomainRegistrationOrder) -> tuple[list[str], str | None]:
    from app.utils.domain_nameservers import parse_order_nameservers

    return parse_order_nameservers(order)


def is_legacy_resellerclub_order(order: DomainRegistrationOrder) -> bool:
    """
    True only for domains that are still exclusively at ResellerClub.

    Some rows incorrectly store the same numeric id in both
    ``resellerclub_order_id`` and ``open_provider_domain_id``. Prefer live
    OpenProvider signals (status / nameserver source / platform NS) so those
    domains are not blocked from HubRegistrar DNS.
    """
    rc_id = str(order.resellerclub_order_id or "").strip()
    if not rc_id:
        return False

    op_status = str(getattr(order, "open_provider_status", None) or "").strip().upper()
    if op_status in {"ACT", "ACTIVE"}:
        return False

    ns_hosts, ns_source = _parse_order_nameservers(order)
    if (ns_source or "").strip().lower() == "openprovider":
        return False

    try:
        from app.integrations.openprovider.client import is_platform_nameserver_set

        if ns_hosts and is_platform_nameserver_set(ns_hosts):
            return False
    except Exception:
        pass

    op_id = str(order.open_provider_domain_id or "").strip()
    if not op_id or op_id.startswith("DEMO-") or op_id == rc_id:
        return True
    return False


def sanitize_customer_registrar_message(message: str) -> str:
    """Never expose registrar vendor names (OpenProvider / ResellerClub) to customers."""
    text = (message or "").strip()
    if not text:
        return text
    lower = text.lower()
    if (
        "openprovider" in lower
        or "open provider" in lower
        or "resellerclub" in lower
        or "reseller club" in lower
        or "legacy_resellerclub" in lower
    ):
        if "dns" in lower or "nameserver" in lower:
            return (
                "DNS and nameserver management is not available for this domain yet. "
                "Contact HubRegistrar support if you need help."
            )
        return "This action is not available for this domain right now. Please contact HubRegistrar support."
    return text


def _order_registrar(order: DomainRegistrationOrder) -> str:
    """Resolve registrar for eligibility checks. Runtime DNS always uses OpenProvider."""
    if is_legacy_resellerclub_order(order):
        return "resellerclub"
    op_id = str(order.open_provider_domain_id or "").strip()
    if op_id and not op_id.startswith("DEMO-"):
        return "openprovider"
    if order.resellerclub_order_id:
        return "resellerclub"
    from app.core.config import settings
    return settings.domain_registrar()


def dnssec_management_supported(order: DomainRegistrationOrder) -> bool:
    """
    Single source of truth for DNSSEC enable/disable eligibility.

    DNSSEC can only be managed through our platform when the domain's registrar
    supports DNSSEC management AND the domain is using our default nameservers
    (required by the underlying integration). This is the exact condition enforced
    by the DNSSEC toggle endpoint, so the UI's disabled state and the backend's
    acceptance are always in agreement.
    """
    registrar = _order_registrar(order)
    if registrar != "openprovider":
        return False

    from app.integrations import domain_registrar
    reg = domain_registrar.active_registrar()
    if not (hasattr(reg, "_default_nameservers") and hasattr(reg, "update_dnssec")):
        return False

    hosts, _ = _parse_order_nameservers(order)
    if hasattr(reg, "is_platform_nameserver_set"):
        return bool(reg.is_platform_nameserver_set(hosts))
    if not hosts:
        return True
    defaults = reg._default_nameservers()
    if not defaults:
        return True
    normalized_hosts = sorted(h.lower() for h in hosts)
    normalized_defaults = sorted(ns.lower() for ns in defaults)
    return normalized_hosts == normalized_defaults


def build_domain_management(order: DomainRegistrationOrder) -> dict[str, Any]:
    """
    Customer-facing DNS / domain management hints for paid registration orders.
    """
    from app.integrations import domain_registrar
    reg = domain_registrar.active_registrar()
    life = registration_lifecycle_status(order)
    ns_hosts, ns_source = _parse_order_nameservers(order)
    if not ns_hosts:
        if hasattr(reg, "_default_nameservers"):
            ns_hosts = reg._default_nameservers()

    paid = bool(order.razorpay_payment_id)
    can_manage = paid and life in (
        "registration_confirmed",
        "registration_pending",
        "payment_success",
    )

    supports_dnssec = dnssec_management_supported(order)

    # Customer-facing DNS always stays on HubRegistrar. Never expose registrar
    # control-panel URLs (e.g. OpenProvider CP) to buyers — white-label.
    cobrother_dns_url = _order_dns_url(order.id) if can_manage else None

    can_manage_dns = False
    # DNS zone management requires platform NS on a non-legacy order.
    if can_manage and ns_hosts and not is_legacy_resellerclub_order(order):
        if hasattr(reg, "is_platform_nameserver_set"):
            can_manage_dns = bool(reg.is_platform_nameserver_set(ns_hosts))
        elif hasattr(reg, "_default_nameservers"):
            defaults = reg._default_nameservers()
            if defaults:
                normalized_hosts = sorted(h.lower() for h in ns_hosts)
                normalized_defaults = sorted(ns.lower() for ns in defaults)
                can_manage_dns = normalized_hosts == normalized_defaults

    dns_steps: list[str] = []
    if can_manage:
        if can_manage_dns:
            dns_steps = [
                "Open DNS & Nameservers on this order page in HubRegistrar.",
                "Add A, CNAME, or MX records to point your website or email.",
                "Keep HubRegistrar managed nameservers unless you move DNS to another provider.",
            ]
        else:
            dns_steps = [
                "Open DNS & Nameservers on this order page in HubRegistrar.",
                "If you use custom nameservers, manage DNS at that provider.",
                "To manage records in HubRegistrar, switch nameservers back to HubRegistrar managed DNS.",
            ]

    return {
        "available": can_manage,
        "domain": order.fqdn,
        "lifecycleStatus": life,
        "nameservers": ns_hosts or None,
        "nameserverSource": ns_source,
        # Backward-compatible name: always HubRegistrar DNS tab when available.
        "customerPanelUrl": cobrother_dns_url,
        "cobrotherDnsUrl": cobrother_dns_url,
        # Do not leak vendor control panels to customers.
        "registrarControlPanelUrl": None,
        "loginEmail": order.buyer_email,
        "expiresAt": order.expires_at.isoformat() if order.expires_at else None,
        "dnsSteps": dns_steps,
        "canManageDns": can_manage_dns,
        "supportsDnssec": supports_dnssec,
        "legacyResellerClub": is_legacy_resellerclub_order(order),
    }


def _can_resend_verification(order: DomainRegistrationOrder) -> bool:
    return (
        _normalize_icann_status(order.icann_verification_status) == "PENDING"
        and bool(order.open_provider_domain_id)
        and order.status == RegistrationOrderStatus.ACTIVE
    )


def _build_next_steps(order: DomainRegistrationOrder) -> list[str]:
    life = registration_lifecycle_status(order)
    steps: list[str] = []
    if life == "awaiting_payment":
        steps.append("Complete payment to start domain registration.")
    elif life in ("payment_success", "registration_pending"):
        steps.append(
            "We are registering your domain with the registrar. "
            "This page will update automatically; you can also refresh your orders list.",
        )
    elif life == "registration_confirmed":
        icann = _normalize_icann_status(order.icann_verification_status)
        if icann == "PENDING":
            steps.append(
                f"Check {order.buyer_email or 'your registrant email'} for a registrar "
                "verification email and click Verify (public WHOIS lookup alone does not verify)."
            )
        elif icann == "SUSPENDED":
            steps.append("Registrant email verification failed or expired. Contact support.")
        elif icann == "VERIFIED":
            steps.append("Registrant email is verified with the registry.")
        ns_hosts, _ = _parse_order_nameservers(order)
        if ns_hosts:
            steps.append(
                f"Nameservers: {', '.join(ns_hosts)}. "
                "Manage DNS records on the DNS & Nameservers tab of this order page.",
            )
        else:
            steps.append(
                "Manage DNS and nameservers on the DNS & Nameservers tab of this order page.",
            )
        if order.expires_at:
            steps.append(f"Registrar expiry (approx.): {order.expires_at.date().isoformat()}.")
    elif life == "registration_failed":
        steps.append("Registration failed after payment. Use Retry on the storefront or contact support.")
    return steps


class DomainRegistrationFollowup:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._orders = DomainRegistrationOrderRepository(session)

    async def sync_from_registrar(
        self,
        order: DomainRegistrationOrder,
    ) -> tuple[bool, DomainRegistrationOrder]:
        """
        Poll active registrar for order confirmation, expiry, and RAA status.
        Returns (confirmed_active, order).
        """
        from app.integrations import domain_registrar
        reg = domain_registrar.active_registrar()

        # Legacy ResellerClub test domains are not in OpenProvider — skip sync.
        if is_legacy_resellerclub_order(order):
            logger.info(
                "Skipping OpenProvider sync for legacy ResellerClub order=%s domain=%s",
                order.id,
                order.fqdn,
            )
            return False, order

        rc_order_id = order.open_provider_domain_id
        if not rc_order_id or str(rc_order_id).startswith("DEMO-"):
            return False, order
        if not reg.is_configured():
            return False, order

        try:
            details = await reg.get_domain_all_details(str(rc_order_id))
        except Exception as exc:
            logger.warning("Registrar sync failed order=%s: %s", order.id, exc)
            return False, order

        order.last_registrar_sync_at = datetime.now(timezone.utc)
        order.icann_verification_status = reg.parse_raa_verification_status(details)
        expiry = reg.parse_expiry_from_details(details)
        if expiry is not None:
            order.expires_at = expiry

        # Registrar is the source of truth for nameservers: refresh the DB copy
        # so validation (DNS records, DNSSEC) never acts on stale data.
        # Skip when the registrar returns nothing so we never clobber a known-good value.
        if hasattr(reg, "parse_nameservers_from_details"):
            try:
                ns_hosts = reg.parse_nameservers_from_details(details) or []
            except Exception as exc:
                logger.warning(
                    "Nameserver parse failed during sync order=%s: %s", order.id, exc,
                )
                ns_hosts = []
            if ns_hosts:
                from app.utils.domain_nameservers import (
                    parse_order_nameservers,
                    set_order_nameservers,
                )

                current_hosts, _ = parse_order_nameservers(order)
                if sorted(current_hosts) != sorted(ns_hosts):
                    logger.info(
                        "Nameserver sync order=%s domain=%s: %s -> %s",
                        order.id,
                        order.fqdn,
                        current_hosts,
                        ns_hosts,
                    )
                if hasattr(reg, "is_platform_nameserver_set") and reg.is_platform_nameserver_set(ns_hosts):
                    ns_src = "openprovider"
                else:
                    ns_src = "custom"
                set_order_nameservers(order, ns_hosts, ns_src)

        current = reg.order_details_current_status(details)
        if current:
            order.open_provider_status = current

        confirmed = reg.is_registration_confirmed(details)
        if confirmed:
            # A completed OpenProvider transfer must also be reflected in the
            # transfer lifecycle state (transfer_status PENDING -> COMPLETED),
            # not just the registration status. The customer-facing transfer
            # UI (status badge, DNS & Email tab unlocking, transfer status row)
            # is driven by transferStatus, so leaving it PENDING keeps a
            # successfully transferred domain stuck on "TRANSFER PENDING" with
            # DNS & Nameservers / Email & Security locked. This branch also
            # corrects orders that were already promoted to ACTIVE by an
            # earlier sync whose transfer_status was never updated.
            is_transfer = bool(
                order.transfer_status and order.transfer_status != "NONE"
            )
            if is_transfer and order.transfer_status != "COMPLETED":
                order.transfer_status = "COMPLETED"
            if order.status != RegistrationOrderStatus.ACTIVE:
                order.status = RegistrationOrderStatus.ACTIVE
                order.completed_at = order.completed_at or datetime.now(timezone.utc)
                order.provision_message = (
                    "Domain transfer completed successfully"
                    if is_transfer
                    else "Domain registration confirmed with registrar"
                )
        elif not confirmed and order.status == RegistrationOrderStatus.REGISTRATION_PENDING:
            order.provision_message = (
                order.provision_message
                or "Registration submitted; waiting for registrar confirmation"
            )

        await self._orders.save(order)

        # Also refresh OpenProvider SSL addon status when present
        await self.sync_ssl_addon(order)

        return confirmed, order

    async def sync_ssl_addon(self, order: DomainRegistrationOrder) -> None:
        """Refresh SSL order status from OpenProvider into dns_records_json.ssl."""
        if not order.dns_records_json:
            return
        try:
            addons = json.loads(order.dns_records_json)
        except Exception:
            return
        if not isinstance(addons, dict):
            return
        ssl = addons.get("ssl")
        if not isinstance(ssl, dict) or not ssl.get("opOrderId"):
            return
        status = str(ssl.get("status") or "").upper()
        if status in {"EXP", "REJ", "FAI"}:
            return
        if status == "ACT" and ssl.get("certificate"):
            return

        from app.integrations import domain_registrar

        reg = domain_registrar.active_registrar()
        if not reg.is_configured() or not hasattr(reg, "get_ssl_order"):
            return
        try:
            details = await reg.get_ssl_order(int(ssl["opOrderId"]))
        except Exception as exc:
            logger.warning("SSL sync failed order=%s ssl=%s: %s", order.id, ssl.get("opOrderId"), exc)
            return

        new_status = str(details.get("status") or ssl.get("status") or "").upper()
        ssl["status"] = new_status or ssl.get("status")
        ssl["active"] = new_status == "ACT"
        if details.get("expiration_date"):
            ssl["expiresAt"] = details.get("expiration_date")
        if details.get("product_name"):
            ssl["productName"] = details.get("product_name")
        if details.get("common_name"):
            ssl["commonName"] = details.get("common_name")
        if details.get("certificate"):
            ssl["certificate"] = details.get("certificate")
        if details.get("intermediate_certificate"):
            ssl["intermediateCertificate"] = details.get("intermediate_certificate")
        if details.get("root_certificate"):
            ssl["rootCertificate"] = details.get("root_certificate")
        if details.get("additional_data") is not None:
            ssl["additionalData"] = details.get("additional_data")
        if details.get("email_approver"):
            ssl["approverEmail"] = details.get("email_approver")
        ssl["lastSyncedAt"] = datetime.now(timezone.utc).isoformat()

        # Keep legacy flags in sync for older UI readers
        addons["ssl"] = ssl
        if ssl["active"]:
            addons["ssl_active"] = True
            addons["ssl_expiry"] = ssl.get("expiresAt")
        else:
            addons["ssl_active"] = False

        order.dns_records_json = json.dumps(addons)
        await self._orders.save(order)

    async def run_pending_reconcile_batch(self) -> int:
        """Reconcile REGISTRATION_PENDING orders without re-registering."""
        limit = max(1, settings.DOMAIN_REGISTRATION_RECONCILE_BATCH_LIMIT)
        orders = await self._orders.list_pending_reconcile_candidates(limit=limit)
        confirmed = 0
        for order in orders:
            was_confirmed, order = await self.sync_from_registrar(order)
            if was_confirmed:
                confirmed += 1
                await self.send_lifecycle_emails(order)
        if orders:
            await self._session.commit()
        return confirmed

    async def run_transfer_pending_reconcile(self) -> int:
        """Retry paid domain transfers that were never submitted to the registrar.

        Covers the "payment captured but provider temporarily unavailable" case:
        the order is PAYMENT_COMPLETED / PENDING with a captured payment and no
        OpenProvider domain id. Each tick re-attempts the submission via
        _provision_transfer, which (a) succeeds → REGISTRATION_PENDING and the
        normal reconcile path takes over, or (b) the registrar rejects → the
        order becomes PROVISION_FAILED / FAILED and drops out of this set, or
        (c) the registrar is still unreachable → stays PENDING and is retried
        up to the provision-attempt limit. Never duplicates Razorpay charges.
        """
        limit = max(1, settings.DOMAIN_REGISTRATION_RECONCILE_BATCH_LIMIT)
        candidates = await self._orders.list_transfer_reconcile_candidates(limit=limit)
        processed = 0
        for raw in candidates:
            order = await self._orders.get_by_id_for_update(raw.id)
            if order is None:
                continue
            if (
                order.status != RegistrationOrderStatus.PAYMENT_COMPLETED
                or order.transfer_status != "PENDING"
                or not order.razorpay_payment_id
                or str(order.open_provider_domain_id or "").strip()
            ):
                continue
            from app.entity.user.app_user import AppUser

            buyer = await self._session.get(AppUser, order.buyer_id)
            if buyer is None:
                logger.warning(
                    "transfer.reconcile.buyer_missing order_id=%s domain=%s",
                    order.id,
                    order.fqdn,
                )
                continue
            try:
                from app.service.domain.domain_registration_service import (
                    DomainRegistrationService,
                )

                svc = DomainRegistrationService(self._session)
                await svc._provision_transfer(order, buyer=buyer)
                processed += 1
            except Exception as exc:
                # _provision_transfer already records the failure state and
                # commits; only log here so one bad row never aborts the batch.
                logger.warning(
                    "transfer.reconcile.attempt_failed order_id=%s domain=%s err=%s",
                    order.id,
                    order.fqdn,
                    exc,
                )
        if processed:
            await self._session.commit()
        return processed

    async def run_stale_pending_alerts(self) -> int:
        hours = max(1.0, settings.DOMAIN_REGISTRATION_PENDING_ALERT_HOURS)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        stale = await self._orders.list_stale_pending(cutoff=cutoff, limit=50)
        for order in stale:
            logger.error(
                "Domain registration stuck pending order_id=%s domain=%s rc_order=%s hours>=%s",
                order.id,
                order.fqdn,
                order.open_provider_domain_id,
                hours,
            )
        return len(stale)

    async def recover_stale_registration_pending(self) -> dict[str, int]:
        """Deterministic exit for stuck REGISTRATION_PENDING / PAYMENT_COMPLETED.

        Safety: only UPDATEs status/provision_message — never deletes rows.
        Clock uses PENDING_SINCE stamp (not updated_at) so reconcile saves cannot
        postpone the timeout forever.
        """
        minutes = max(1.0, float(settings.DOMAIN_REGISTRATION_PENDING_TIMEOUT_MINUTES))
        cutoff = _utc_now() - timedelta(minutes=minutes)
        # Fetch a wider pending set; filter by pending_since in Python.
        candidates = await self._orders.list_open_pending(limit=50)
        stats = {
            "examined": 0,
            "reconciled_active": 0,
            "retried": 0,
            "deferred_pending": 0,
            "failed": 0,
        }
        if not candidates:
            return stats

        for order in candidates:
            if order.status not in (
                RegistrationOrderStatus.REGISTRATION_PENDING,
                RegistrationOrderStatus.PAYMENT_COMPLETED,
            ):
                continue

            # ── Transfer safety guard ─────────────────────────────────────────
            # Domain transfers (transfer_status != NONE) legitimately stay
            # REGISTRATION_PENDING for days while OpenProvider completes them.
            # They must NEVER be failed by the registration stale-pending
            # timeout. Transfers are reconciled only through the safe
            # sync_from_registrar / run_pending_reconcile_batch paths.
            if order.transfer_status and order.transfer_status != "NONE":
                continue

            # Stamp first so reconcile updated_at bumps cannot hide age, and so
            # legacy rows get a fair 10-minute window from first recovery sighting.
            before_msg = order.provision_message
            stamp_registration_pending_since(order)
            if order.provision_message != before_msg:
                await self._orders.save(order)

            since = pending_since_of(order)
            if since is None or since >= cutoff:
                continue

            stats["examined"] += 1
            domain = order.fqdn
            age_minutes = (_utc_now() - since).total_seconds() / 60.0

            logger.warning(
                "stale_pending.recovery.start order_id=%s domain=%s status=%s "
                "op_id=%s age_minutes≈%s timeout_minutes=%s",
                order.id,
                domain,
                order.status,
                order.open_provider_domain_id,
                round(age_minutes, 1),
                minutes,
            )

            # Path A: have registrar id → reconcile only (never re-register blindly).
            if order.open_provider_domain_id:
                confirmed, order = await self.sync_from_registrar(order)
                if confirmed or order.status == RegistrationOrderStatus.ACTIVE:
                    await self.send_lifecycle_emails(order)
                    stats["reconciled_active"] += 1
                    logger.info(
                        "stale_pending.recovery.activated order_id=%s domain=%s",
                        order.id,
                        domain,
                    )
                    continue

                order.status = RegistrationOrderStatus.PROVISION_FAILED
                order.provision_message = (
                    f"Registration left REGISTRATION_PENDING for over {minutes:.0f} minutes "
                    f"without OpenProvider confirmation (op_id={order.open_provider_domain_id}). "
                    "Marked PROVISION_FAILED by stale-pending recovery. Admin can retry provision."
                )
                await self._orders.save(order)
                await self.send_lifecycle_emails(order)
                stats["failed"] += 1
                logger.error(
                    "stale_pending.recovery.marked_failed order_id=%s domain=%s reason=NO_OP_CONFIRMATION",
                    order.id,
                    domain,
                )
                continue

            # Path B: no OP id — one more provision attempt, then fail only if still no id.
            try:
                await self._retry_provision(order)
                stats["retried"] += 1
            except Exception as exc:
                logger.exception(
                    "stale_pending.recovery.provision_retry_failed order_id=%s domain=%s err=%s",
                    order.id,
                    domain,
                    exc,
                )

            order = await self._orders.get_by_id(order.id) or order
            if order.status == RegistrationOrderStatus.ACTIVE:
                stats["reconciled_active"] += 1
                continue
            if order.status == RegistrationOrderStatus.PROVISION_FAILED:
                stats["failed"] += 1
                continue
            if order.status == RegistrationOrderStatus.REFUNDED:
                continue

            # Retry just submitted to OP — stamp pending clock and defer fail to later tick.
            if order.open_provider_domain_id and order.status in (
                RegistrationOrderStatus.REGISTRATION_PENDING,
                RegistrationOrderStatus.PAYMENT_COMPLETED,
            ):
                if order.status != RegistrationOrderStatus.REGISTRATION_PENDING:
                    order.status = RegistrationOrderStatus.REGISTRATION_PENDING
                # Fresh OP submit: reset pending clock so we don't fail same window.
                order.provision_message = None
                stamp_registration_pending_since(order)
                await self._orders.save(order)
                confirmed, order = await self.sync_from_registrar(order)
                if confirmed or order.status == RegistrationOrderStatus.ACTIVE:
                    await self.send_lifecycle_emails(order)
                    stats["reconciled_active"] += 1
                else:
                    stats["deferred_pending"] += 1
                    logger.info(
                        "stale_pending.recovery.deferred_after_retry order_id=%s domain=%s op_id=%s",
                        order.id,
                        domain,
                        order.open_provider_domain_id,
                    )
                continue

            if order.status in (
                RegistrationOrderStatus.REGISTRATION_PENDING,
                RegistrationOrderStatus.PAYMENT_COMPLETED,
            ):
                order.status = RegistrationOrderStatus.PROVISION_FAILED
                order.provision_message = (
                    f"Registration stuck without OpenProvider domain id for over "
                    f"{minutes:.0f} minutes (status was pending/payment-completed). "
                    "Marked PROVISION_FAILED by stale-pending recovery. Admin can retry provision."
                )
                await self._orders.save(order)
                await self.send_lifecycle_emails(order)
                stats["failed"] += 1
                logger.error(
                    "stale_pending.recovery.marked_failed order_id=%s domain=%s "
                    "reason=NO_OP_DOMAIN_ID_AFTER_TIMEOUT",
                    order.id,
                    domain,
                )

        if candidates:
            await self._session.commit()
            if stats["examined"] or stats["failed"] or stats["retried"] or stats["deferred_pending"]:
                logger.info("stale_pending.recovery.finished %s", stats)
        return stats

    async def _retry_provision(self, order: DomainRegistrationOrder) -> None:
        """One provision attempt for stale recovery (isolated for tests/mocks)."""
        from app.service.domain.domain_registration_service import (
            DomainRegistrationService,
        )

        await DomainRegistrationService(self._session).provision_order(order)

    def order_detail_dict(self, order: DomainRegistrationOrder) -> dict[str, Any]:
        life = registration_lifecycle_status(order)
        icann = _normalize_icann_status(order.icann_verification_status)
        rc_id = order.open_provider_domain_id
        active = order.status == RegistrationOrderStatus.ACTIVE
        ns_hosts, ns_source = _parse_order_nameservers(order)
        mgmt = build_domain_management(order)
        summary = {
            "id": str(order.id),
            "domain": order.fqdn,
            **order_gst_payload(order),
            "periodYears": int(order.period_years or 1),
            "status": order.status.value,
            "lifecycleStatus": life,
            "createdAt": order.created_at.isoformat(),
            "completedAt": order.completed_at.isoformat() if order.completed_at else None,
            "expiresAt": order.expires_at.isoformat() if order.expires_at else None,
            "message": order.provision_message,
            "registrarOrderId": rc_id,
            "razorpayOrderId": order.razorpay_order_id,
            "razorpayPaymentId": order.razorpay_payment_id,
            "icannVerificationStatus": icann,
            "raaVerificationStatus": icann if icann != "UNKNOWN" else None,
            "buyerEmail": order.buyer_email,
            "buyerFullName": order.buyer_full_name,
            "buyerPhone": order.buyer_phone,
            "buyerGstin": getattr(order, "buyer_gstin", None),
            "taxInvoiceNumber": getattr(order, "tax_invoice_number", None),
            "invoiceNumber": getattr(order, "tax_invoice_number", None),
            "street": order.street,
            "city": order.city,
            "state": order.state,
            "zipCode": order.zip_code,
            "country": order.country,
            "canResendVerification": _can_resend_verification(order),
            "canRetry": not active
            and order.status
            in (
                RegistrationOrderStatus.PROVISION_FAILED,
                RegistrationOrderStatus.PAYMENT_COMPLETED,
                RegistrationOrderStatus.REGISTRATION_PENDING,
            ),
            "registrarSandbox": settings.openprovider_use_sandbox(),
            "supportsDnssec": mgmt.get("supportsDnssec", False),
            "nextSteps": _build_next_steps(order),
            "orderDetailUrl": _order_detail_url(order.id),
            "demoMode": bool(rc_id and str(rc_id).startswith("DEMO-")),
            "nameservers": ns_hosts or None,
            "nameserverSource": ns_source,
            "registrarControlPanelUrl": mgmt.get("registrarControlPanelUrl"),
            "domainManagement": mgmt,
            "canManageDomain": mgmt["available"],
            "customerPanelUrl": mgmt.get("customerPanelUrl"),
            "dnsRecords": order.dns_records_json,
            "isPremium": bool(getattr(order, "is_premium", False)),
            "registryTier": str(getattr(order, "registry_tier", None) or "standard"),
            "providerUnitPriceInr": getattr(order, "provider_unit_price_inr", None),
            "customerUnitPriceInr": order.quoted_unit_price_inr,
            "priceSource": order.price_source,
            # Transfer fields — REQUIRED for the frontend transfer UI branch.
            # list_my_orders/_order_summary already emits these; order_detail_dict
            # was missing them which caused order.isTransfer === undefined in the
            # frontend, so the dedicated transfer details UI was never rendered.
            "isTransfer": order.transfer_status is not None and order.transfer_status != "NONE",
            "transferStatus": order.transfer_status,
            # Only an unpaid/cancelled transfer attempt may be retried as a
            # payment; a captured payment or in-flight/failed/refunded attempt
            # is never retryable here (see retry_transfer_payment guards).
            "canRetryPayment": (
                order.transfer_status not in (None, "NONE")
                and not order.razorpay_payment_id
                and order.status
                in (
                    RegistrationOrderStatus.CREATED,
                    RegistrationOrderStatus.EXPIRED,
                    RegistrationOrderStatus.PAYMENT_FAILED,
                )
            ),
        }
        return summary

    async def get_enriched_order(
        self,
        order_id: uuid.UUID,
        *,
        buyer: AppUser,
        sync: bool = True,
    ) -> dict[str, Any]:
        order = await self._orders.get_by_id(order_id)
        if order is None or order.buyer_id != buyer.id:
            raise AppException("Order not found.", status_code=404)
        if sync:
            await self.sync_from_registrar(order)
            await self.send_lifecycle_emails(order)
            await self._session.commit()
            order = await self._orders.get_by_id(order_id)
        assert order is not None
        return self.order_detail_dict(order)

    async def resend_verification(
        self,
        order_id: uuid.UUID,
        *,
        buyer: AppUser,
    ) -> dict[str, Any]:
        order = await self._orders.get_by_id(order_id)
        if order is None or order.buyer_id != buyer.id:
            raise AppException("Order not found.", status_code=404)
        if not _can_resend_verification(order):
            raise AppException(
                "Verification resend is not available for this order.",
                status_code=400,
            )
        from app.integrations import domain_registrar
        reg = domain_registrar.active_registrar()

        try:
            ok = await reg.resend_raa_verification(
                email=str(order.buyer_email),
                handle=str(order.open_provider_handle),
            )
        except Exception as exc:
            raise AppException(str(exc), status_code=502) from exc
        return {
            "success": ok,
            "message": "Verification email resent to the registrant address."
            if ok
            else "Registrar did not accept the resend request.",
        }

    async def send_lifecycle_emails(self, order: DomainRegistrationOrder) -> None:
        """Idempotent transactional emails based on order flags."""
        if not order.buyer_email:
            return

        life = registration_lifecycle_status(order)
        detail_url = _order_detail_url(order.id)

        if order.razorpay_payment_id and not order.email_receipt_sent:
            try:
                await MailService.send_domain_registration_receipt_email(
                    to_email=str(order.buyer_email),
                    fqdn=order.fqdn,
                    amount_inr=float(order.price_inr),
                    razorpay_payment_id=order.razorpay_payment_id,
                    order_detail_url=detail_url,
                )
                order.email_receipt_sent = True
                await self._orders.save(order)
            except Exception as exc:
                logger.warning("Receipt email failed order=%s: %s", order.id, exc)

        if (
            order.status == RegistrationOrderStatus.REGISTRATION_PENDING
            and not order.email_submitted_sent
        ):
            try:
                await MailService.send_domain_registration_submitted_email(
                    to_email=str(order.buyer_email),
                    fqdn=order.fqdn,
                    order_detail_url=detail_url,
                    is_transfer=order.transfer_status is not None and order.transfer_status != "NONE",
                )
                order.email_submitted_sent = True
                await self._orders.save(order)
            except Exception as exc:
                logger.warning("Submitted email failed order=%s: %s", order.id, exc)

        if life == "registration_confirmed" and not order.email_active_sent:
            try:
                mgmt = build_domain_management(order)
                await MailService.send_domain_registration_active_email(
                    to_email=str(order.buyer_email),
                    fqdn=order.fqdn,
                    order_detail_url=hubregistrar_order_detail_url(order.id),
                    expires_at=(
                        order.expires_at.isoformat() if order.expires_at else None
                    ),
                    registered_at=(
                        (order.completed_at or order.created_at).isoformat()
                        if (order.completed_at or order.created_at)
                        else None
                    ),
                    nameservers=mgmt.get("nameservers"),
                    manage_dns_url=hubregistrar_order_dns_url(order.id),
                )
                order.email_active_sent = True
                await self._orders.save(order)
            except Exception as exc:
                logger.warning("Active email failed order=%s: %s", order.id, exc)

        icann = _normalize_icann_status(order.icann_verification_status)
        if (
            life == "registration_confirmed"
            and icann == "PENDING"
            and not order.email_raa_pending_sent
        ):
            try:
                await MailService.send_domain_registration_raa_pending_email(
                    to_email=str(order.buyer_email),
                    fqdn=order.fqdn,
                    registrant_email=str(order.buyer_email),
                    order_detail_url=detail_url,
                )
                order.email_raa_pending_sent = True
                await self._orders.save(order)
            except Exception as exc:
                logger.warning("RAA pending email failed order=%s: %s", order.id, exc)

        if should_send_registration_failed_email(order):
            try:
                is_transfer = (
                    order.transfer_status is not None
                    and order.transfer_status != "NONE"
                )
                await MailService.send_domain_registration_failed_email(
                    to_email=str(order.buyer_email),
                    fqdn=order.fqdn,
                    message=order.provision_message or "Registration failed.",
                    order_detail_url=detail_url,
                    is_transfer=is_transfer,
                )
                order.email_failed_sent = True
                await self._orders.save(order)
            except Exception as exc:
                logger.warning("Failed email failed order=%s: %s", order.id, exc)
