"""Outbound-only email notifications via SMTP (spec: notify a customer when
their ticket is approved/rejected). No inbound channel - see
docs/SECURITY.md for why that's out of scope.

`Integration.base_url` is the SMTP host (e.g. "smtp.sendgrid.net"),
`config.smtp_port` (default 587) and `config.use_tls` (default true)
control the connection, `config.from_email` is the From address, and
credentials (`auth_type` should be `basic`) carry `username`/`password`.
Uses stdlib `smtplib` in a thread rather than adding an async SMTP
dependency - this app sends a handful of notification emails, not a
mail queue.
"""

from __future__ import annotations

import asyncio
import json
import smtplib
from email.message import EmailMessage

from app.domain.exceptions import IntegrationError
from app.domain.models import Integration
from app.integrations.crypto import decrypt_secret
from app.observability.logging import get_logger

logger = get_logger(__name__)


def _send_sync(
    *, host: str, port: int, use_tls: bool, username: str, password: str, from_email: str, to: str,
    subject: str, body: str,
) -> None:
    message = EmailMessage()
    message["From"] = from_email
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(host, port, timeout=10) as smtp:
        if use_tls:
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(message)


class EmailClient:
    def __init__(self, integration: Integration) -> None:
        self._integration = integration

    async def send(self, *, to: str, subject: str, body: str) -> None:
        try:
            creds = json.loads(decrypt_secret(self._integration.encrypted_credentials))
        except json.JSONDecodeError as exc:
            raise IntegrationError(
                f"Integration '{self._integration.name}' has corrupted credentials"
            ) from exc

        config = self._integration.config
        from_email = config.get("from_email") or creds.get("username", "")
        try:
            await asyncio.to_thread(
                _send_sync,
                host=self._integration.base_url,
                port=int(config.get("smtp_port", 587)),
                use_tls=bool(config.get("use_tls", True)),
                username=creds.get("username", ""),
                password=creds.get("password", ""),
                from_email=from_email,
                to=to,
                subject=subject,
                body=body,
            )
        except OSError as exc:
            raise IntegrationError(f"Failed to send email via '{self._integration.name}': {exc}") from exc
