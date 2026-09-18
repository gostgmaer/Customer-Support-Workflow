"""End-to-end: an escalated ticket automatically gets a JIRA issue (when a
JIRA integration is configured), the issue key/url show up on the ticket,
and approving/rejecting posts a comment back to JIRA. The JIRA API itself
is mocked with respx - no real JIRA instance involved. Also covers the
"no JIRA configured" case staying silently unaffected (spec: automatic
hooks fail open, see app.integrations.hooks).
"""

import uuid

import pytest
import respx
from httpx import Response


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


async def _create_jira_integration(client, admin_token: str) -> None:
    response = await client.post(
        "/api/v1/admin/integrations",
        json={
            "name": "Auto-create JIRA",
            "type": "jira",
            "base_url": "https://example.atlassian.net",
            "auth_type": "basic",
            "credentials": {"username": "bot@example.com", "password": "token"},
            "config": {"project_key": "SUP"},
        },
        headers=_headers(admin_token),
    )
    assert response.status_code == 201


@pytest.mark.asyncio
@respx.mock
async def test_escalation_auto_creates_a_jira_issue(client, auth_token, seeded_customer, admin_staff_token):
    respx.post("https://example.atlassian.net/rest/api/2/issue").mock(
        return_value=Response(201, json={"key": "SUP-1"})
    )
    await _create_jira_integration(client, admin_staff_token)

    conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
    result = await _post_message(
        client, auth_token, conversation_id, "I think someone accessed my account without permission."
    )
    assert result["requires_human"] is True

    ticket_id = result.get("ticket_id")
    assert ticket_id, "SECURITY escalations should file a ticket"

    ticket_response = await client.get(
        f"/api/v1/support/tickets/{ticket_id}", headers=_headers(admin_staff_token)
    )
    assert ticket_response.status_code == 200
    ticket = ticket_response.json()
    assert ticket["external_ref"] == "SUP-1"
    assert ticket["external_url"] == "https://example.atlassian.net/browse/SUP-1"


@pytest.mark.asyncio
@respx.mock
async def test_escalation_without_jira_configured_leaves_ticket_unaffected(
    client, auth_token, seeded_customer, admin_staff_token
):
    """No JIRA integration exists for this tenant - the ticket must still
    be created normally, with no external_ref, and no attempt to hit the
    network (respx has no routes registered, so any HTTP call would
    itself fail the test)."""
    conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
    result = await _post_message(
        client, auth_token, conversation_id, "I think someone accessed my account without permission."
    )
    ticket_id = result.get("ticket_id")
    assert ticket_id

    ticket_response = await client.get(
        f"/api/v1/support/tickets/{ticket_id}", headers=_headers(admin_staff_token)
    )
    ticket = ticket_response.json()
    assert ticket["external_ref"] is None


@pytest.mark.asyncio
@respx.mock
async def test_approve_posts_a_comment_to_the_linked_jira_issue(
    client, auth_token, seeded_customer, admin_staff_token
):
    respx.post("https://example.atlassian.net/rest/api/2/issue").mock(
        return_value=Response(201, json={"key": "SUP-2"})
    )
    comment_route = respx.post("https://example.atlassian.net/rest/api/2/issue/SUP-2/comment").mock(
        return_value=Response(201, json={})
    )
    await _create_jira_integration(client, admin_staff_token)

    conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
    await _post_message(
        client, auth_token, conversation_id, "The product arrived damaged. I want my money back."
    )
    second = await _post_message(client, auth_token, conversation_id, "Yes, please confirm the refund.")
    assert second["status"] == "awaiting_approval"
    ticket_id = second["ticket_id"]

    approve_response = await client.post(
        f"/api/v1/support/tickets/{ticket_id}/approve",
        json={"workflow_run_id": second["workflow_run_id"]},
        headers=_headers(admin_staff_token),
    )
    assert approve_response.status_code == 200
    assert comment_route.called
