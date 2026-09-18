"""Inbound webhook signature verification (spec: Phase 8.4, extended in
Phase 9.4 for Stripe and Phase 10.1 for replay protection on the
storefront scheme).

Every other integration in this codebase is outbound-only (this app calls
JIRA/WooCommerce/MCP/OpenAPI/Stripe) - a webhook is the first inbound
caller, so it needs its own authentication story: there's no staff JWT to
check, just a shared secret the admin configured on the `Integration` row
(`config.webhook_secret`, alongside `role`/`auto_execute_reads` - the
same free-JSON pattern, no schema change needed) and a signature the
caller computes with it.

Both inbound schemes (`verify_webhook_signature` for the storefront
route, `verify_stripe_signature` for Stripe's own) now share the same
`t=<unix timestamp>,v1=<hex>` wire format and replay-protection posture
(a tolerance window, multiple `v1=` values supported during a secret
rotation) via the shared `_parse_timestamped_signature` helper.
`verify_signature` is the storefront route's original, payload-only
scheme - no longer used by any route, kept only as a record of what
Phase 8.4 shipped before Phase 10.1's replay-protection fix.
"""

from __future__ import annotations

import hashlib
import hmac
import time


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """`signature` is the hex-encoded HMAC-SHA256 of `payload` keyed by
    `secret` - `hmac.compare_digest` for a timing-safe comparison, the
    standard library's own answer to this exact problem.

    Superseded in production by `verify_webhook_signature` below (spec:
    Phase 10.1) - this original scheme has no replay protection at all
    (the signature covers the payload only, no timestamp). Kept defined
    and tested as a record of the prior scheme; no route calls it
    anymore.
    """
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _parse_timestamped_signature(header: str) -> tuple[int, list[str]] | None:
    """Shared `t=<unix timestamp>,v1=<hex>[,v1=<hex>...]` parsing for both
    `verify_webhook_signature` and `verify_stripe_signature` - the header
    shape and timestamp/multi-signature handling are identical between
    the two schemes; only the signed-payload HMAC construction differs
    (in practice, it doesn't - both use the same `f"{timestamp}.".encode()
    + payload` construction - but they stay separate functions since one
    is this app's own scheme and the other is Stripe's, and there's no
    guarantee they'll always agree)."""
    parts: dict[str, list[str]] = {}
    for item in header.split(","):
        if "=" not in item:
            continue
        key, _, value = item.partition("=")
        parts.setdefault(key.strip(), []).append(value.strip())

    timestamps = parts.get("t")
    signatures = parts.get("v1")
    if not timestamps or not signatures:
        return None

    try:
        timestamp = int(timestamps[0])
    except ValueError:
        return None
    return timestamp, signatures


def verify_webhook_signature(
    payload: bytes, header: str, secret: str, *, tolerance_seconds: int = 300
) -> bool:
    """This app's own inbound-webhook signing scheme (storefront events,
    spec: Phase 10.1), sharing Stripe's exact wire format
    (`t=<unix timestamp>,v1=<hex HMAC-SHA256 of "{timestamp}.{payload}">`,
    multiple `v1=` values supported during a secret rotation) rather than
    inventing a second bespoke one - reusing a format callers may already
    know, and letting this function share `_parse_timestamped_signature`
    with `verify_stripe_signature`. Replaces `verify_signature` above,
    which had no replay protection; this is a breaking change to the
    storefront webhook's header contract (see docs/ARCHITECTURE.md /
    docs/SECURITY.md) - accepted as a hard cutover since the only real
    caller today is the committed `demo_storefront/fire_webhook.py`,
    updated alongside this change.
    """
    if not secret or not header:
        return False

    parsed = _parse_timestamped_signature(header)
    if parsed is None:
        return False
    timestamp, signatures = parsed
    if abs(time.time() - timestamp) > tolerance_seconds:
        return False

    signed_payload = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in signatures)


def verify_stripe_signature(
    payload: bytes, header: str, secret: str, *, tolerance_seconds: int = 300
) -> bool:
    """Stripe's own webhook signing scheme (spec: Phase 9.4) - the
    `Stripe-Signature` header is `t=<unix timestamp>,v1=<hex HMAC-SHA256
    of "{timestamp}.{payload}", keyed by the endpoint's signing secret>`
    (and may carry other `v1=`-prefixed values during a secret rotation -
    any one matching is sufficient, per Stripe's own verification
    algorithm). `tolerance_seconds` rejects a stale/replayed signature
    even if it's otherwise valid - Stripe's own libraries default to a
    300-second window, adopted here unchanged. `verify_webhook_signature`
    above (spec: Phase 10.1) now gives this app's own storefront webhook
    the identical replay-protection posture.
    """
    if not secret or not header:
        return False

    parsed = _parse_timestamped_signature(header)
    if parsed is None:
        return False
    timestamp, signatures = parsed
    if abs(time.time() - timestamp) > tolerance_seconds:
        return False

    signed_payload = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in signatures)
