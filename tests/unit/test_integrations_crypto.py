"""app.integrations.crypto: Integration.encrypted_credentials round-trips,
and a JWT_SECRET change makes old ciphertext fail closed with a clear
IntegrationError rather than a confusing low-level exception."""

import pytest

from app.domain.exceptions import IntegrationError


def test_encrypt_decrypt_round_trips():
    from app.integrations.crypto import decrypt_secret, encrypt_secret

    ciphertext = encrypt_secret("super-secret-api-key")
    assert ciphertext != "super-secret-api-key"
    assert decrypt_secret(ciphertext) == "super-secret-api-key"


def test_decrypt_fails_closed_after_key_rotation(monkeypatch):
    from app.config import get_settings
    from app.integrations.crypto import decrypt_secret, encrypt_secret

    ciphertext = encrypt_secret("super-secret-api-key")

    monkeypatch.setenv("JWT_SECRET", "a-completely-different-secret")
    get_settings.cache_clear()
    try:
        with pytest.raises(IntegrationError):
            decrypt_secret(ciphertext)
    finally:
        get_settings.cache_clear()


# --- spec: Phase 9.1c - CREDENTIALS_ENCRYPTION_KEY decouples this from JWT_SECRET ---


def test_credentials_encryption_key_takes_precedence_when_set(monkeypatch):
    from app.config import get_settings
    from app.integrations.crypto import decrypt_secret, encrypt_secret

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", "a-dedicated-credentials-key")
    get_settings.cache_clear()
    try:
        ciphertext = encrypt_secret("super-secret-api-key")
        assert decrypt_secret(ciphertext) == "super-secret-api-key"
    finally:
        get_settings.cache_clear()


def test_blank_credentials_encryption_key_falls_back_to_jwt_secret(monkeypatch):
    """Regression protection for the zero-setup default - a deployment
    that has never set CREDENTIALS_ENCRYPTION_KEY must keep decrypting
    existing rows exactly as before this setting existed."""
    from app.config import get_settings
    from app.integrations.crypto import decrypt_secret, encrypt_secret

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    try:
        ciphertext = encrypt_secret("super-secret-api-key")
        assert decrypt_secret(ciphertext) == "super-secret-api-key"
    finally:
        get_settings.cache_clear()


def test_jwt_secret_rotation_no_longer_breaks_decryption_once_key_is_set(monkeypatch):
    """The actual bug this phase fixes: with a dedicated
    CREDENTIALS_ENCRYPTION_KEY set, rotating JWT_SECRET must NOT
    invalidate previously-stored integration credentials."""
    from app.config import get_settings
    from app.integrations.crypto import decrypt_secret, encrypt_secret

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", "a-dedicated-credentials-key")
    get_settings.cache_clear()
    ciphertext = encrypt_secret("super-secret-api-key")

    monkeypatch.setenv("JWT_SECRET", "a-completely-different-secret")
    get_settings.cache_clear()
    try:
        assert decrypt_secret(ciphertext) == "super-secret-api-key"
    finally:
        get_settings.cache_clear()
