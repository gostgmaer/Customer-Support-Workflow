"""End-to-end: approving/rejecting a ticket emails the customer, when an
SMTP integration is configured. smtplib.SMTP is monkeypatched - no real
mail server involved.
"""

import uuid

import pytest


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _post_message(client, token: str, conversation_id: str, message: str) -> dict:
    response = await client.post(
        "/api/v1/support/messages",
        json={
            "conversation_id": conversation_id,
            "message_id": f"msg_{uuid.uuid4().hex[:8]}",
            "message": message,
            "channel": "web",
        },
        headers=_headers(token),
    )
    assert response.status_code == 200
    return response.json()


class _FakeSMTP:
    sent: list[dict] = []

    def __init__(self, host, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self):
        pass

    def login(self, username, password):
        pass

    def send_message(self, message):
        _FakeSMTP.sent.append({"to": message["To"], "subject": message["Subject"]})


@pytest.mark.asyncio
async def test_reject_emails_the_customer(
    client, auth_token, seeded_customer, admin_staff_token, monkeypatch
):
    _FakeSMTP.sent = []
    monkeypatch.setattr("app.integrations.email.smtplib.SMTP", _FakeSMTP)

    create_response = await client.post(
        "/api/v1/admin/integrations",
        json={
            "name": "Notifications",
            "type": "smtp",
            "base_url": "smtp.example.com",
            "auth_type": "basic",
            "credentials": {"username": "bot", "password": "app-password"},
            "config": {"from_email": "support@example.com"},
        },
        headers=_headers(admin_staff_token),
    )
    assert create_response.status_code == 201

    conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
    await _post_message(
        client, auth_token, conversation_id, "The product arrived damaged. I want my money back."
    )
    second = await _post_message(client, auth_token, conversation_id, "Yes, please confirm the refund.")
    ticket_id = second["ticket_id"]

    reject_response = await client.post(
        f"/api/v1/support/tickets/{ticket_id}/reject",
        json={"workflow_run_id": second["workflow_run_id"], "reason": "Outside policy window"},
        headers=_headers(admin_staff_token),
    )
    assert reject_response.status_code == 200

    assert len(_FakeSMTP.sent) == 1
    assert _FakeSMTP.sent[0]["to"] == seeded_customer["email"]
    assert "rejected" in _FakeSMTP.sent[0]["subject"]
