"""Map OperationsService ORM rows to API responses."""

from __future__ import annotations

from app.entity.operations.operations_service_entity import OperationsService
from app.model.operations.operations_service_response import OperationsServiceResponse


def build_operations_service_response(row: OperationsService) -> OperationsServiceResponse:
    return OperationsServiceResponse(
        id=row.id,
        name=row.name,
        category=row.category,
        description=row.description,
        price=row.price,
        is_available=row.is_available,
        icon=row.icon,
        display_order=row.display_order,
        skills=row.skills,
        service_type=row.service_type,
        government_fees_applicable=row.government_fees_applicable,
        government_fee_text=row.government_fee_text,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
