"""Map OperationsServiceRequest ORM rows to API payloads."""

from __future__ import annotations

from app.entity.operations.operations_service_request_entity import OperationsServiceRequest
from app.service.admin.admin_serializers import user_brief


def build_operations_service_request_response(row: OperationsServiceRequest) -> dict:
    return {
        "id": str(row.id),
        "operationsServiceId": str(row.operations_service_id),
        "userId": str(row.user_id),
        "requestType": row.request_type,
        "serviceType": row.service_type,
        "billingPeriod": row.billing_period,
        "category": row.operations_service.category if getattr(row, "operations_service", None) else None,
        "serviceName": row.service_name,
        "quotedPrice": float(row.quoted_price or 0),
        "fullName": row.full_name,
        "email": row.email,
        "phone": row.phone,
        "companyName": row.company_name,
        "cityState": row.city_state,
        "message": row.message,
        "preferredTimeline": row.preferred_timeline,
        "status": row.status,
        "razorpayOrderId": row.razorpay_order_id,
        "razorpayPaymentId": row.razorpay_payment_id,
        "razorpaySignature": row.razorpay_signature,
        "paymentStatus": row.payment_status,
        "paymentAmountInr": float(row.payment_amount_inr) if row.payment_amount_inr is not None else None,
        "contactStatus": row.contact_status,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
        "user": user_brief(row.user),
    }
