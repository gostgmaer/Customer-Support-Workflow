"""app.security.webhooks.verify_signature (spec: Phase 8.4, superseded in
production by verify_webhook_signature - spec: Phase 10.1)."""

from __future__ import annotations

import hashlib
import hmac
import time

from app.security.webhooks import verify_signature, verify_webhook_signature


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature_verifies():
    body = b'{"event": "order.refunded", "order_id": "ORD-1"}'
    secret = "shh"

    assert verify_signature(body, _sign(secret, body), secret) is True


def test_wrong_secret_fails():
    body = b'{"event": "order.refunded", "order_id": "ORD-1"}'

    assert verify_signature(body, _sign("shh", body), "different-secret") is False


def test_tampered_body_fails():
    body = b'{"event": "order.refunded", "order_id": "ORD-1"}'
    secret = "shh"
    signature = _sign(secret, body)

    assert verify_signature(b'{"event": "order.refunded", "order_id": "ORD-2"}', signature, secret) is False


def test_missing_signature_fails():
    assert verify_signature(b"{}", "", "shh") is False


def test_missing_secret_fails():
    assert verify_signature(b"{}", "somesignature", "") is False


def _sign_timestamped(secret: str, body: bytes, timestamp: int) -> str:
    signed_payload = f"{timestamp}.".encode() + body
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


class TestVerifyWebhookSignature:
    """spec: Phase 10.1 - the storefront webhook's replacement scheme,
    sharing Stripe's own t=/v1= wire format and replay-protection
    posture (see tests/unit/test_stripe_webhook_signature.py)."""

    _SECRET = "shh"
    _BODY = b'{"event": "order.refunded", "order_id": "ORD-1"}'

    def test_valid_signature_verifies(self):
        header = _sign_timestamped(self._SECRET, self._BODY, int(time.time()))
        assert verify_webhook_signature(self._BODY, header, self._SECRET) is True

    def test_wrong_secret_fails(self):
        header = _sign_timestamped(self._SECRET, self._BODY, int(time.time()))
        assert verify_webhook_signature(self._BODY, header, "different-secret") is False

    def test_tampered_body_fails(self):
        header = _sign_timestamped(self._SECRET, self._BODY, int(time.time()))
        tampered = b'{"event": "order.refunded", "order_id": "ORD-2"}'
        assert verify_webhook_signature(tampered, header, self._SECRET) is False

    def test_stale_timestamp_outside_tolerance_fails(self):
        old_header = _sign_timestamped(self._SECRET, self._BODY, int(time.time()) - 1000)
        assert verify_webhook_signature(self._BODY, old_header, self._SECRET, tolerance_seconds=300) is False

    def test_missing_header_fails(self):
        assert verify_webhook_signature(self._BODY, "", self._SECRET) is False

    def test_missing_secret_fails(self):
        header = _sign_timestamped(self._SECRET, self._BODY, int(time.time()))
        assert verify_webhook_signature(self._BODY, header, "") is False

    def test_malformed_header_fails(self):
        assert verify_webhook_signature(self._BODY, "not-a-valid-header", self._SECRET) is False

    def test_multiple_v1_values_accepts_any_matching_one(self):
        timestamp = int(time.time())
        real_signature = _sign_timestamped(self._SECRET, self._BODY, timestamp).split("v1=")[1]
        header = f"t={timestamp},v1=deadbeef,v1={real_signature}"
        assert verify_webhook_signature(self._BODY, header, self._SECRET) is True
