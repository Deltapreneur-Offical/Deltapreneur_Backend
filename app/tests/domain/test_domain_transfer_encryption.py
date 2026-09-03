"""Auth code encryption round-trip."""

from app.service.security.auth_code_encryption_service import decrypt_secret, encrypt_secret


def test_encrypt_decrypt_round_trip():
    plain = "Xy9-Auth-Code-1234"
    cipher = encrypt_secret(plain)
    assert cipher != plain
    assert decrypt_secret(cipher) == plain


def test_mask_account():
    from app.service.security.auth_code_encryption_service import mask_account

    assert mask_account("1234567890").endswith("7890")
    assert "*" in mask_account("1234567890")
