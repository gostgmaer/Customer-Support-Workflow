"""JIRA Cloud REST API v2 client. Auth is `basic` (email + API token - the
standard JIRA Cloud pattern), `config` must include `project_key`
(the JIRA project issues are filed under) and may include `issue_type`
(default "Task").
"""

from __future__ import annotations

from app.domain.exceptions import IntegrationError
from app.domain.models import Integration
from app.integrations.base import build_http_client, short_response_body
from app.observability.logging import get_logger

logger = get_logger(__name__)

_PRIORITY_MAP = {"CRITICAL": "Highest", "HIGH": "High", "MEDIUM": "Medium", "LOW": "Low"}


class JiraClient:
    def __init__(self, integration: Integration) -> None:
        self._integration = integration
        self._project_key = integration.config.get("project_key")
        if not self._project_key:
            raise IntegrationError(f"JIRA integration '{integration.name}' is missing 'project_key'")
        self._issue_type = integration.config.get("issue_type", "Task")

    async def create_issue(self, *, summary: str, description: str, priority: str) -> dict[str, str]:
        fields: dict[str, object] = {
            "project": {"key": self._project_key},
            "summary": summary[:250],
            "description": description,
            "issuetype": {"name": self._issue_type},
        }
        jira_priority = _PRIORITY_MAP.get(priority)
        if jira_priority:
            fields["priority"] = {"name": jira_priority}

        async with build_http_client(self._integration) as client:
            response = await client.post("/rest/api/2/issue", json={"fields": fields})
        if response.status_code >= 400:
            raise IntegrationError(
                f"JIRA issue creation failed ({response.status_code}): {short_response_body(response.text)}"
            )
        data = response.json()
        key = data["key"]
        return {"key": key, "url": f"{self._integration.base_url.rstrip('/')}/browse/{key}"}

    async def add_comment(self, issue_key: str, body: str) -> None:
        async with build_http_client(self._integration) as client:
            response = await client.post(f"/rest/api/2/issue/{issue_key}/comment", json={"body": body})
        if response.status_code >= 400:
            raise IntegrationError(
                f"JIRA comment failed ({response.status_code}): {short_response_body(response.text)}"
            )
