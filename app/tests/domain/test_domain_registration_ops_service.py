from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import ProgrammingError

from app.service.domain.domain_registration_ops_service import DomainRegistrationOpsService


@pytest.mark.asyncio
async def test_run_provision_retries_skips_when_schema_is_missing(monkeypatch):
    session = SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock())
    service = DomainRegistrationOpsService(session)
    service._orders.list_provision_retry_candidates = AsyncMock(
        side_effect=ProgrammingError(
            "SELECT ...",
            {},
            RuntimeError("column domain_registration_orders.subtotal_inr does not exist"),
        ),
    )

    count = await service.run_provision_retries(max_attempts=3)

    assert count == 0
    session.rollback.assert_awaited_once()
