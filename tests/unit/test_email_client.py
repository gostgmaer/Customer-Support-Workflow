"""app.integrations.email.EmailClient - smtplib.SMTP is monkeypatched, no
real mail server involved."""

import pytest

from app.db.base import DEFAULT_TENANT_ID
from app.domain.exceptions import IntegrationError
from app.domain.models import Integration
from app.integrations.base import encode_credentials
from app.integrations.email import EmailClient


def _smtp_integration(**config_overrides) -> Integration:
    config = {"from_email": "support@example.com"}
    config.update(config_overrides)
    return Integration(
        id="int_smtp_1",
        tenant_id=DEFAULT_TENANT_ID,
        name="Test SMTP",
        type="smtp",
        base_url="smtp.example.com",
        auth_type="basic",
        encrypted_credentials=encode_credentials({"username": "bot", "password": "app-password"}),
        config=config,
        enabled=True,
        created_by="staff_1",
    )


class _FakeSMTP:
    sent: list[dict] = []
    logins: list[tuple[str, str]] = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self):
        pass

    def login(self, username, password):
        _FakeSMTP.logins.append((username, password))

    def send_message(self, message):
        _FakeSMTP.sent.append({"to": message["To"], "from": message["From"], "subject": message["Subject"]})


@pytest.mark.asyncio
async def test_send_uses_configured_from_and_credentials(monkeypatch):
    _FakeSMTP.sent = []
    _FakeSMTP.logins = []
    monkeypatch.setattr("app.integrations.email.smtplib.SMTP", _FakeSMTP)

    client = EmailClient(_smtp_integration())
    await client.send(to="alice@example.com", subject="Ticket approved", body="...")

    assert _FakeSMTP.sent == [
        {"to": "alice@example.com", "from": "support@example.com", "subject": "Ticket approved"}
    ]
    assert _FakeSMTP.logins == [("bot", "app-password")]


@pytest.mark.asyncio
async def test_send_raises_integration_error_on_connection_failure(monkeypatch):
    class _FailingSMTP(_FakeSMTP):
        def __enter__(self):
            raise OSError("connection refused")

    monkeypatch.setattr("app.integrations.email.smtplib.SMTP", _FailingSMTP)

    client = EmailClient(_smtp_integration())
    with pytest.raises(IntegrationError):
        await client.send(to="alice@example.com", subject="x", body="x")
