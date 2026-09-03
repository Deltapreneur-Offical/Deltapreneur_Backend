"""ResellPortal Integration Client Module.

Re-exports ResellPortalClient and get_resellportal_client for exact filename compatibility.
"""

from app.integrations.resellportal.client import ResellPortalClient, get_resellportal_client

__all__ = ["ResellPortalClient", "get_resellportal_client"]
