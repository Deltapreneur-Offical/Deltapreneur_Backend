"""Security checks for auth-code handling."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.service.domain.domain_transfer_event_service import DomainTransferEventService
from app.service.security.auth_code_encryption_service import encrypt_secret
from app.utils.transfer_enums import TransferEventType


@pytest.mark.asyncio
async def test_event_log_redacts_auth_code_in_payload():
    session = MagicMock()
    service = DomainTransferEventService(session)
    service._repo.create = AsyncMock(return_value=MagicMock())

    await service.log(
        uuid.uuid4(),
        TransferEventType.AUTH_SUBMITTED,
        payload={"authCode": "SECRET"},
    )

    created = service._repo.create.await_args[0][0]
    assert "SECRET" not in (created.payload_json or "")
    assert "REDACTED" in (created.payload_json or "")


def test_encrypted_auth_code_not_equal_to_plaintext():
    plain = "MyEppCode123!"
    cipher = encrypt_secret(plain)
    assert cipher != plain
    assert len(cipher) > len(plain)
