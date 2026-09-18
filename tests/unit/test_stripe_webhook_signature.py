"""app.security.webhooks.verify_stripe_signature (spec: Phase 9.4) -
Stripe's own `t=<timestamp>,v1=<hmac>` scheme, genuinely different from
the plain-hex `verify_signature` used by the storefront webhook.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from app.security.webhooks import verify_stripe_signature

_SECRET = "whsec_test_secret"
_PAYLOAD = b'{"id": "evt_1", "type": "payment_intent.succeeded"}'


def _sign(payload: bytes, secret: str, timestamp: int) -> str:
    signed_payload = f"{timestamp}.".encode() + payload
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def test_valid_signature_verifies():
    header = _sign(_PAYLOAD, _SECRET, int(time.time()))
    assert verify_stripe_signature(_PAYLOAD, header, _SECRET) is True


def test_wrong_secret_fails():
    header = _sign(_PAYLOAD, _SECRET, int(time.time()))
    assert verify_stripe_signature(_PAYLOAD, header, "wrong-secret") is False


def test_tampered_payload_fails():
    header = _sign(_PAYLOAD, _SECRET, int(time.time()))
    assert verify_stripe_signature(b'{"id": "evt_2"}', header, _SECRET) is False


def test_stale_timestamp_outside_tolerance_fails():
    old_header = _sign(_PAYLOAD, _SECRET, int(time.time()) - 1000)
    assert verify_stripe_signature(_PAYLOAD, old_header, _SECRET, tolerance_seconds=300) is False


def test_timestamp_within_tolerance_succeeds():
    header = _sign(_PAYLOAD, _SECRET, int(time.time()) - 100)
    assert verify_stripe_signature(_PAYLOAD, header, _SECRET, tolerance_seconds=300) is True


def test_missing_header_fails():
    assert verify_stripe_signature(_PAYLOAD, "", _SECRET) is False


def test_missing_secret_fails():
    header = _sign(_PAYLOAD, _SECRET, int(time.time()))
    assert verify_stripe_signature(_PAYLOAD, header, "") is False


def test_malformed_header_fails():
    assert verify_stripe_signature(_PAYLOAD, "not-a-valid-header", _SECRET) is False


def test_multiple_v1_values_accepts_any_matching_one():
    """Stripe sends multiple v1= values during a secret rotation window -
    any one matching is sufficient."""
    timestamp = int(time.time())
    real_signature = _sign(_PAYLOAD, _SECRET, timestamp).split("v1=")[1]
    header = f"t={timestamp},v1=deadbeef,v1={real_signature}"
    assert verify_stripe_signature(_PAYLOAD, header, _SECRET) is True
