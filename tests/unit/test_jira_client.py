"""app.integrations.jira.JiraClient - HTTP calls mocked with respx (no real
JIRA instance)."""

import pytest
import respx
from httpx import Response

from app.db.base import DEFAULT_TENANT_ID
from app.domain.exceptions import IntegrationError
from app.domain.models import Integration
from app.integrations.base import encode_credentials
from app.integrations.jira import JiraClient


def _jira_integration(**config_overrides) -> Integration:
    config = {"project_key": "SUP"}
    config.update(config_overrides)
    return Integration(
        id="int_jira_1",
        tenant_id=DEFAULT_TENANT_ID,
        name="Test JIRA",
        type="jira",
        base_url="https://example.atlassian.net",
        auth_type="basic",
        encrypted_credentials=encode_credentials({"username": "bot@example.com", "password": "token"}),
        config=config,
        enabled=True,
        created_by="staff_1",
    )


@pytest.mark.asyncio
@respx.mock
async def test_create_issue_returns_key_and_url():
    respx.post("https://example.atlassian.net/rest/api/2/issue").mock(
        return_value=Response(201, json={"key": "SUP-42", "id": "10001"})
    )
    client = JiraClient(_jira_integration())

    result = await client.create_issue(summary="Refund needs approval", description="...", priority="HIGH")

    assert result == {"key": "SUP-42", "url": "https://example.atlassian.net/browse/SUP-42"}


@pytest.mark.asyncio
@respx.mock
async def test_create_issue_raises_on_error_response():
    respx.post("https://example.atlassian.net/rest/api/2/issue").mock(
        return_value=Response(400, text="project key is invalid")
    )
    client = JiraClient(_jira_integration())

    with pytest.raises(IntegrationError):
        await client.create_issue(summary="x", description="x", priority="LOW")


@pytest.mark.asyncio
@respx.mock
async def test_add_comment_posts_to_the_right_issue():
    route = respx.post("https://example.atlassian.net/rest/api/2/issue/SUP-42/comment").mock(
        return_value=Response(201, json={})
    )
    client = JiraClient(_jira_integration())

    await client.add_comment("SUP-42", "Approved by staff_jane.")

    import json

    assert route.called
    assert json.loads(route.calls.last.request.content) == {"body": "Approved by staff_jane."}


def test_missing_project_key_raises_immediately():
    integration = _jira_integration()
    integration.config = {}
    with pytest.raises(IntegrationError):
        JiraClient(integration)
