"""Domain API models."""

from app.model.domain.domain_request import CreateDomainRequest, UpdateDomainRequest
from app.model.domain.domain_response import DomainListResponse, DomainResponse

__all__ = [
    "CreateDomainRequest",
    "UpdateDomainRequest",
    "DomainResponse",
    "DomainListResponse",
]
