"""Registrar instruction content for Path A."""

from app.service.domain.domain_transfer_instruction_service import (
    get_transfer_instructions,
    normalize_registrar_key,
)


def test_normalize_registrar_key_godaddy():
    assert normalize_registrar_key("GoDaddy Inc.") == "godaddy"


def test_get_transfer_instructions_default():
    data = get_transfer_instructions("Unknown Registrar")
    assert data["registrarKey"] == "default"
    assert len(data["steps"]) >= 3
