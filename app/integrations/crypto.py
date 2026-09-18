"""Encryption for `Integration.encrypted_credentials`.

spec: Phase 9.1c - the Fernet key comes from `CREDENTIALS_ENCRYPTION_KEY`
when set; when blank (the zero-setup default, and every deployment that
predates this setting) it falls back to the original behavior of
deriving the key from `JWT_SECRET` (SHA-256 -> urlsafe base64) - no
forced re-encryption, no migration, existing rows keep decrypting
exactly as before. The fallback's original problem is still real for
anyone who hasn't set the new var: rotating `JWT_SECRET` makes every
stored integration credential undecryptable, the same way it already
invalidates every issued JWT. A production deployment should set
`CREDENTIALS_ENCRYPTION_KEY` once (see docs/SECURITY.md for rotation
guidance) so the two secrets can be rotated independently.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings
from app.domain.exceptions import IntegrationError


def _fernet() -> Fernet:
    settings = get_settings()
    key_material = settings.credentials_encryption_key or settings.jwt_secret
    digest = hashlib.sha256(key_material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise IntegrationError(
            "Stored integration credentials could not be decrypted - CREDENTIALS_ENCRYPTION_KEY "
            "(or JWT_SECRET, if that key is unset) may have changed since they were saved. "
            "Re-enter this integration's credentials."
        ) from exc
