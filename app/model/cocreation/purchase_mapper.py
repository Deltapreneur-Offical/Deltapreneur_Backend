"""Map SoftwarePurchase rows to frontend-friendly dicts."""

from __future__ import annotations

from app.entity.cocreation.software_purchase_entity import SoftwarePurchase
from app.model.cocreation.software_mapper import build_software_response
from app.utils.cocreation_enums import SoftwarePurchaseCompletionStatus


def build_purchase_response(purchase: SoftwarePurchase) -> dict:
    software = purchase.software
    sw_payload = None
    if software is not None:
        sw = build_software_response(software, is_owner=False, hide_github_from_public=True)
        sw_dict = sw.model_dump(mode="json", by_alias=True)
        if purchase.completion_status == SoftwarePurchaseCompletionStatus.CONFIRMED:
            sw_dict["githubLink"] = software.github_link
        else:
            sw_dict["githubLink"] = None
        sw_payload = sw_dict

    return {
        "id": str(purchase.id),
        "softwareId": str(purchase.software_id),
        "buyerId": str(purchase.buyer_id),
        "buyerFullName": purchase.buyer_full_name,
        "buyerEmail": purchase.buyer_email,
        "buyerPhone": purchase.buyer_phone,
        "paymentStatus": purchase.payment_status.value,
        "completionStatus": purchase.completion_status.value,
        "selectedPlan": purchase.selected_plan.value if purchase.selected_plan else None,
        "expiryDate": purchase.expiry_date.isoformat() if purchase.expiry_date else None,
        "coBrotherOptIn": purchase.co_brother_opt_in,
        "coBrotherHelpPaid": purchase.co_brother_help_paid,
        "grossAmountInr": purchase.gross_amount_inr,
        "soldAt": purchase.sold_at.isoformat() if purchase.sold_at else None,
        "createdAt": purchase.created_at.isoformat() if purchase.created_at else None,
        "software": sw_payload,
    }
