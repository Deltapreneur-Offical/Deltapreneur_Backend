"""Serialize managed acquisitions for admin + unified buyer dashboard."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.entity.cobranding.domain_enquiry_entity import DomainEnquiry
from app.entity.domain.openprovider_managed_acquisition_entity import (
    OpenProviderManagedAcquisition,
)


def _iso(value: Any) -> str | None:
    """Safe ISO serializer — DB drivers / legacy rows may yield str or datetime."""
    if value is None or value is False:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value) if value else None


def _fqdn(domain_name: str, tld_or_ext: str | None) -> str:
    name = (domain_name or "").strip()
    ext = (tld_or_ext or "").strip()
    if not ext:
        return name
    if ext.startswith("."):
        return f"{name}{ext}"
    if "." in name:
        return name
    return f"{name}.{ext.lstrip('.')}"


def build_acquisition_timeline(
    *,
    status: str,
    created_at: datetime | None,
    in_progress_at: datetime | None = None,
    accepted_at: datetime | None = None,
    completed_at: datetime | None = None,
    declined_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    Dynamic timeline from status + timestamps.
    FE renders this array only — no hardcoded step lists.
    """
    status_u = (status or "").upper()
    steps: list[dict[str, Any]] = []

    def add(key: str, label: str, at: datetime | None, reached: bool) -> None:
        steps.append(
            {
                "key": key,
                "label": label,
                "at": _iso(at),
                "reached": bool(reached),
            }
        )

    add(
        "submitted",
        "Acquisition request submitted",
        created_at,
        True,
    )

    under_review_reached = status_u in {
        "PENDING",
        "IN_PROGRESS",
        "ACCEPTED",
        "COMPLETED",
        "DECLINED",
    }
    add(
        "under_review",
        "Under review",
        created_at if under_review_reached else None,
        under_review_reached,
    )

    in_progress_reached = bool(in_progress_at) or status_u in {
        "IN_PROGRESS",
        "ACCEPTED",
        "COMPLETED",
    }
    add(
        "in_progress",
        "HubRegistrar team contacting you",
        in_progress_at or (created_at if status_u == "IN_PROGRESS" else None),
        in_progress_reached and status_u != "DECLINED",
    )

    accepted_reached = bool(accepted_at) or status_u in {"ACCEPTED", "COMPLETED"}
    add(
        "accepted",
        "Acquisition in progress",
        accepted_at,
        accepted_reached,
    )

    if status_u == "DECLINED" or declined_at:
        add("declined", "Request declined", declined_at, True)
    else:
        completed_reached = bool(completed_at) or status_u == "COMPLETED"
        add("completed", "Acquisition completed", completed_at, completed_reached)

    return steps


def serialize_op_managed_acquisition(
    row: OpenProviderManagedAcquisition,
) -> dict[str, Any]:
    fqdn = _fqdn(row.domain_name, row.tld)
    return {
        "id": str(row.id),
        "channel": "OPENPROVIDER",
        "domainName": fqdn,
        "requestedPrice": float(row.payable_inr or row.quoted_price_inr or 0),
        "quotedPriceInr": float(row.quoted_price_inr or 0),
        "payableInr": float(row.payable_inr or 0),
        "gstInr": float(row.gst_inr or 0),
        "periodYears": int(row.period_years or 1),
        "status": row.status,
        "adminNotes": row.admin_notes,
        "latestAdminMessage": row.admin_notes,
        "isRegistryPremium": bool(row.is_registry_premium),
        "registryTier": row.registry_tier,
        "fullName": row.full_name,
        "email": row.email,
        "phone": row.phone,
        "message": row.message,
        "createdAt": _iso(row.created_at),
        "updatedAt": _iso(row.updated_at),
        "inProgressAt": _iso(row.in_progress_at),
        "acceptedAt": _iso(row.accepted_at),
        "completedAt": _iso(row.completed_at),
        "declinedAt": _iso(row.declined_at),
        "timeline": build_acquisition_timeline(
            status=row.status,
            created_at=row.created_at,
            in_progress_at=row.in_progress_at,
            accepted_at=row.accepted_at,
            completed_at=row.completed_at,
            declined_at=row.declined_at,
        ),
        "buyer": {
            "id": str(row.user_id),
            "firstname": getattr(row.user, "firstname", None) if row.user else None,
            "lastname": getattr(row.user, "lastname", None) if row.user else None,
            "email": getattr(row.user, "email", None) if row.user else row.email,
        },
    }


def serialize_marketplace_enquiry_as_acquisition(
    enquiry: DomainEnquiry,
) -> dict[str, Any] | None:
    """Map DomainEnquiry into unified buyer acquisition DTO (no marketplace labels in UI)."""
    if enquiry is None:
        return None
    # Skip pipeline placeholders
    if (
        enquiry.message == "Listed premium domain (Pending buyer enquiry)"
        and enquiry.full_name == "No buyer enquiry yet"
    ):
        return None

    listing = enquiry.domain_listing
    fqdn = ""
    price = 0.0
    if listing is not None:
        fqdn = _fqdn(listing.domain_name or "", listing.domain_extension or "")
        price = float(listing.asking_price or 0)

    status = (enquiry.status or "PENDING").upper()
    return {
        "id": str(enquiry.id),
        "channel": "MARKETPLACE",
        "domainName": fqdn,
        "requestedPrice": price,
        "quotedPriceInr": price,
        "payableInr": price,
        "gstInr": 0.0,
        "periodYears": None,
        "status": status,
        "adminNotes": enquiry.admin_notes,
        "latestAdminMessage": enquiry.admin_notes,
        "isRegistryPremium": None,
        "registryTier": None,
        "fullName": enquiry.full_name,
        "email": enquiry.email,
        "phone": enquiry.phone,
        "message": enquiry.message,
        "createdAt": _iso(enquiry.created_at),
        "updatedAt": _iso(getattr(enquiry, "updated_at", None)),
        "inProgressAt": _iso(enquiry.in_progress_at),
        "acceptedAt": None,
        "completedAt": _iso(enquiry.completed_at),
        "declinedAt": _iso(enquiry.declined_at),
        "timeline": build_acquisition_timeline(
            status=status,
            created_at=enquiry.created_at,
            in_progress_at=enquiry.in_progress_at,
            accepted_at=None if status not in {"ACCEPTED", "COMPLETED"} else enquiry.in_progress_at,
            completed_at=enquiry.completed_at,
            declined_at=enquiry.declined_at,
        ),
    }


def buyer_facing_acquisition(dto: dict[str, Any]) -> dict[str, Any]:
    """Strip internal channel / registry fields from buyer responses."""
    out = dict(dto)
    out.pop("channel", None)
    out.pop("isRegistryPremium", None)
    out.pop("registryTier", None)
    out.pop("buyer", None)
    return out
