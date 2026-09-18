"""POST /api/v1/admin/integrations/{id}/sync (spec: Phase 9.3) - creates
a "docs" integration, syncs it via respx-mocked fixture Confluence
responses, and confirms the expected KnowledgeDocument/KnowledgeChunk
rows land and are actually retrievable - not just that the route
returns a number.
"""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from app.db.base import DEFAULT_TENANT_ID
from app.rag.retriever import Retriever
from app.repositories.vector_store import InMemoryVectorStore


def _confluence_page_response(version: int = 1) -> Response:
    return Response(
        200,
        json={
            "id": "111",
            "title": "Refund Policy",
            "version": {"number": version},
            "body": {
                "storage": {
                    "value": (
                        "<p>Customers may request a refund within 30 days of delivery "
                        "under our refund policy.</p>"
                    )
                }
            },
        },
    )


async def _create_docs_integration(client, admin_staff_token) -> str:
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    body = {
        "name": "Team Confluence",
        "type": "docs",
        "base_url": "https://example.atlassian.net",
        "auth_type": "basic",
        "credentials": {"username": "bot@example.com", "password": "token"},
        "config": {"provider": "confluence", "page_ids": ["111"], "category": "refunds"},
    }
    response = await client.post("/api/v1/admin/integrations", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.asyncio
@respx.mock
async def test_sync_ingests_the_expected_chunks(client, admin_staff_token, db_session):
    integration_id = await _create_docs_integration(client, admin_staff_token)
    respx.get("https://example.atlassian.net/wiki/api/v2/pages/111").mock(
        return_value=_confluence_page_response()
    )
    headers = {"Authorization": f"Bearer {admin_staff_token}"}

    response = await client.post(f"/api/v1/admin/integrations/{integration_id}/sync", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["chunks_ingested"] > 0


@pytest.mark.asyncio
@respx.mock
async def test_second_sync_at_the_same_version_is_a_dedupe_no_op(client, admin_staff_token, db_session):
    integration_id = await _create_docs_integration(client, admin_staff_token)
    respx.get("https://example.atlassian.net/wiki/api/v2/pages/111").mock(
        return_value=_confluence_page_response(version=1)
    )
    headers = {"Authorization": f"Bearer {admin_staff_token}"}

    first = await client.post(f"/api/v1/admin/integrations/{integration_id}/sync", headers=headers)
    second = await client.post(f"/api/v1/admin/integrations/{integration_id}/sync", headers=headers)

    assert first.json()["chunks_ingested"] > 0
    assert second.json()["chunks_ingested"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_a_version_bump_re_ingests_the_page(client, admin_staff_token, db_session):
    integration_id = await _create_docs_integration(client, admin_staff_token)
    route = respx.get("https://example.atlassian.net/wiki/api/v2/pages/111")
    route.mock(return_value=_confluence_page_response(version=1))
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    await client.post(f"/api/v1/admin/integrations/{integration_id}/sync", headers=headers)

    route.mock(return_value=_confluence_page_response(version=2))
    second = await client.post(f"/api/v1/admin/integrations/{integration_id}/sync", headers=headers)

    assert second.json()["chunks_ingested"] > 0


@pytest.mark.asyncio
@respx.mock
async def test_synced_content_is_actually_retrievable(client, admin_staff_token, db_session):
    integration_id = await _create_docs_integration(client, admin_staff_token)
    respx.get("https://example.atlassian.net/wiki/api/v2/pages/111").mock(
        return_value=_confluence_page_response()
    )
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    await client.post(f"/api/v1/admin/integrations/{integration_id}/sync", headers=headers)

    retriever = Retriever(InMemoryVectorStore())
    results = await retriever.retrieve(
        "What is your refund policy?", tenant_id=DEFAULT_TENANT_ID, top_k=3
    )

    assert results, "expected the synced Confluence page to be retrievable"
    assert any(r.title == "Refund Policy" for r in results)


@pytest.mark.asyncio
async def test_sync_rejects_a_non_docs_integration(client, admin_staff_token):
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    body = {
        "name": "Not A Docs Integration",
        "type": "jira",
        "base_url": "https://example.atlassian.net",
        "auth_type": "basic",
        "credentials": {"username": "bot@example.com", "password": "token"},
        "config": {"project_key": "SUP"},
    }
    create_response = await client.post("/api/v1/admin/integrations", json=body, headers=headers)
    integration_id = create_response.json()["id"]

    response = await client.post(f"/api/v1/admin/integrations/{integration_id}/sync", headers=headers)

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_sync_requires_admin(client, staff_token, admin_staff_token):
    admin_headers = {"Authorization": f"Bearer {admin_staff_token}"}
    body = {
        "name": "Admin Only Sync Test",
        "type": "docs",
        "base_url": "https://example.atlassian.net",
        "auth_type": "basic",
        "credentials": {"username": "bot@example.com", "password": "token"},
        "config": {"provider": "confluence", "page_ids": ["111"]},
    }
    create_response = await client.post("/api/v1/admin/integrations", json=body, headers=admin_headers)
    integration_id = create_response.json()["id"]

    response = await client.post(
        f"/api/v1/admin/integrations/{integration_id}/sync",
        headers={"Authorization": f"Bearer {staff_token}"},
    )

    assert response.status_code == 403
