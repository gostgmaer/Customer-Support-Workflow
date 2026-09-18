"""Manual test helper for the inbound storefront webhook route (spec:
Phase 8.1, updated in Phase 10.1 for the timestamped signature scheme).

Usage:
    python -m demo_storefront.fire_webhook \\
        --base-url http://localhost:8000 \\
        --integration-id <the connected Integration's id> \\
        --secret <its config.webhook_secret> \\
        --event order.refunded --order-id ORD-1001

Signs with the same `t=<unix timestamp>,v1=<hex HMAC-SHA256 of
"{timestamp}.{body}">` scheme as `app.security.webhooks.verify_webhook_signature`
(shared with Stripe's own wire format, spec: Phase 10.1) - a plain
payload-only hex signature (the original Phase 8.4 scheme) is no longer
accepted by the real route.

Uses only the standard library deliberately - this is a manual demo/test
script, not a runtime dependency of the storefront service itself.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request


def _sign(secret: str, body: bytes) -> str:
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.".encode() + body
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def fire(base_url: str, integration_id: str, secret: str, event: str, order_id: str, data: dict) -> None:
    payload = {"event": event, "order_id": order_id, "data": data}
    body = json.dumps(payload).encode()
    signature = _sign(secret, body)
    url = f"{base_url.rstrip('/')}/api/v1/webhooks/storefront/{integration_id}"
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Webhook-Signature": signature},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            print(response.status, response.read().decode())
    except urllib.error.HTTPError as exc:
        print(exc.code, exc.read().decode())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--integration-id", required=True)
    parser.add_argument("--secret", required=True)
    parser.add_argument("--event", default="order.refunded")
    parser.add_argument("--order-id", default="ORD-1001")
    args = parser.parse_args()

    fire(
        args.base_url,
        args.integration_id,
        args.secret,
        args.event,
        args.order_id,
        {"note": "fired manually via demo_storefront/fire_webhook.py"},
    )


if __name__ == "__main__":
    main()
