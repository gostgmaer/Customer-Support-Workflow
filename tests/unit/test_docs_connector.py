"""app.integrations.docs_connector's ConfluenceClient/NotionClient - HTTP
calls mocked with respx against fixture responses shaped to match each
provider's real, public API documentation (spec: Phase 9.3). No real
Confluence/Notion workspace exists to verify against yet - see
docs/ARCHITECTURE.md's "RAG doc connectors" for the documented
live-verification gap.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import respx
from httpx import Response

from app.db.base import DEFAULT_TENANT_ID
from app.domain.exceptions import IntegrationError
from app.domain.models import Integration
from app.integrations.base import encode_credentials
from app.integrations.docs_connector import (
    ConfluenceClient,
    GoogleDriveClient,
    NotionClient,
    SharePointClient,
    get_docs_client,
)

_FAR_FUTURE_EXPIRY = (datetime.now(UTC) + timedelta(days=365)).isoformat()


def _oauth2_integration(*, base_url: str, provider: str, **config_overrides) -> Integration:
    config = {"provider": provider}
    config.update(config_overrides)
    return Integration(
        id=f"int_{provider}_1",
        tenant_id=DEFAULT_TENANT_ID,
        name=f"Test {provider}",
        type="docs",
        base_url=base_url,
        auth_type="oauth2",
        encrypted_credentials=encode_credentials(
            {"access_token": "at_1", "refresh_token": "rt_1", "expires_at": _FAR_FUTURE_EXPIRY}
        ),
        config=config,
        enabled=True,
        created_by="staff_1",
    )


def _confluence_integration(**config_overrides) -> Integration:
    config = {"provider": "confluence", "space_key": "SUP"}
    config.update(config_overrides)
    return Integration(
        id="int_confluence_1",
        tenant_id=DEFAULT_TENANT_ID,
        name="Test Confluence",
        type="docs",
        base_url="https://example.atlassian.net",
        auth_type="basic",
        encrypted_credentials=encode_credentials({"username": "bot@example.com", "password": "token"}),
        config=config,
        enabled=True,
        created_by="staff_1",
    )


def _notion_integration(**config_overrides) -> Integration:
    config = {"provider": "notion", "database_id": "db-123"}
    config.update(config_overrides)
    return Integration(
        id="int_notion_1",
        tenant_id=DEFAULT_TENANT_ID,
        name="Test Notion",
        type="docs",
        base_url="https://api.notion.com",
        auth_type="bearer",
        encrypted_credentials=encode_credentials({"token": "secret_abc"}),
        config=config,
        enabled=True,
        created_by="staff_1",
    )


def test_get_docs_client_dispatches_on_provider():
    assert isinstance(get_docs_client(_confluence_integration()), ConfluenceClient)
    assert isinstance(get_docs_client(_notion_integration()), NotionClient)


def test_get_docs_client_rejects_unknown_provider():
    integration = _confluence_integration(provider="dropbox")
    try:
        get_docs_client(integration)
        raise AssertionError("expected IntegrationError")
    except IntegrationError:
        pass


def test_get_docs_client_requires_a_session_for_oauth2_providers():
    """spec: Phase 10.4 - google_drive/sharepoint need a session (to
    refresh an expired OAuth2 token); Confluence/Notion never did."""
    integration = _confluence_integration(provider="sharepoint", drive_id="drive-1")
    integration.auth_type = "oauth2"
    try:
        get_docs_client(integration)
        raise AssertionError("expected IntegrationError")
    except IntegrationError:
        pass


def test_confluence_client_requires_space_key_or_page_ids():
    integration = _confluence_integration()
    integration.config = {"provider": "confluence"}
    try:
        ConfluenceClient(integration)
        raise AssertionError("expected IntegrationError")
    except IntegrationError:
        pass


def test_notion_client_requires_database_id_or_page_ids():
    integration = _notion_integration()
    integration.config = {"provider": "notion"}
    try:
        NotionClient(integration)
        raise AssertionError("expected IntegrationError")
    except IntegrationError:
        pass


@respx.mock
async def test_confluence_fetch_documents_by_space_key():
    respx.get("https://example.atlassian.net/wiki/api/v2/spaces").mock(
        return_value=Response(200, json={"results": [{"id": "999", "key": "SUP"}]})
    )
    respx.get("https://example.atlassian.net/wiki/api/v2/spaces/999/pages").mock(
        return_value=Response(
            200,
            json={"results": [{"id": "111", "title": "Refund Policy"}], "_links": {}},
        )
    )
    respx.get("https://example.atlassian.net/wiki/api/v2/pages/111").mock(
        return_value=Response(
            200,
            json={
                "id": "111",
                "title": "Refund Policy",
                "version": {"number": 3},
                "body": {"storage": {"value": "<p>Refunds within <strong>30 days</strong>.</p>"}},
            },
        )
    )
    client = ConfluenceClient(_confluence_integration())

    documents = await client.fetch_documents()

    assert len(documents) == 1
    doc = documents[0]
    assert doc.title == "Refund Policy"
    assert doc.source == "confluence:111"
    assert doc.version == "3"
    assert doc.text == "Refunds within 30 days."


@respx.mock
async def test_confluence_fetch_documents_by_explicit_page_ids_skips_space_lookup():
    space_route = respx.get("https://example.atlassian.net/wiki/api/v2/spaces")
    respx.get("https://example.atlassian.net/wiki/api/v2/pages/222").mock(
        return_value=Response(
            200,
            json={
                "id": "222",
                "title": "Shipping FAQ",
                "version": {"number": 1},
                "body": {"storage": {"value": "<p>Ships in 3-5 days.</p>"}},
            },
        )
    )
    client = ConfluenceClient(_confluence_integration(page_ids=["222"]))

    documents = await client.fetch_documents()

    assert len(documents) == 1
    assert documents[0].source == "confluence:222"
    assert not space_route.called


@respx.mock
async def test_confluence_missing_project_key_analog_raises_immediately():
    """Mirrors JiraClient's own "fails at construction, before any HTTP
    call" contract - proven here by never mocking any route at all."""
    integration = _confluence_integration()
    integration.config = {"provider": "confluence"}
    try:
        ConfluenceClient(integration)
        raise AssertionError("expected IntegrationError")
    except IntegrationError:
        pass


@respx.mock
async def test_confluence_error_response_raises_integration_error():
    respx.get("https://example.atlassian.net/wiki/api/v2/spaces").mock(
        return_value=Response(401, text="Unauthorized")
    )
    client = ConfluenceClient(_confluence_integration())

    try:
        await client.fetch_documents()
        raise AssertionError("expected IntegrationError")
    except IntegrationError:
        pass


@respx.mock
async def test_notion_fetch_documents_by_database_id():
    respx.post("https://api.notion.com/v1/databases/db-123/query").mock(
        return_value=Response(200, json={"results": [{"id": "page-1"}], "has_more": False})
    )
    respx.get("https://api.notion.com/v1/pages/page-1").mock(
        return_value=Response(
            200,
            json={
                "id": "page-1",
                "last_edited_time": "2026-01-01T00:00:00.000Z",
                "properties": {
                    "Name": {"type": "title", "title": [{"plain_text": "Onboarding Guide"}]}
                },
            },
        )
    )
    respx.get("https://api.notion.com/v1/blocks/page-1/children").mock(
        return_value=Response(
            200,
            json={
                "results": [
                    {
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"plain_text": "Welcome to the team."}]},
                    }
                ],
                "has_more": False,
            },
        )
    )
    client = NotionClient(_notion_integration())

    documents = await client.fetch_documents()

    assert len(documents) == 1
    doc = documents[0]
    assert doc.title == "Onboarding Guide"
    assert doc.source == "notion:page-1"
    assert doc.version == "2026-01-01T00:00:00.000Z"
    assert doc.text == "Welcome to the team."


@respx.mock
async def test_notion_fetch_documents_by_explicit_page_ids_skips_database_query():
    database_route = respx.post("https://api.notion.com/v1/databases/db-123/query")
    respx.get("https://api.notion.com/v1/pages/page-2").mock(
        return_value=Response(
            200,
            json={
                "id": "page-2",
                "last_edited_time": "2026-02-01T00:00:00.000Z",
                "properties": {"title": {"type": "title", "title": [{"plain_text": "FAQ"}]}},
            },
        )
    )
    respx.get("https://api.notion.com/v1/blocks/page-2/children").mock(
        return_value=Response(200, json={"results": [], "has_more": False})
    )
    client = NotionClient(_notion_integration(page_ids=["page-2"]))

    documents = await client.fetch_documents()

    assert len(documents) == 1
    assert documents[0].source == "notion:page-2"
    assert not database_route.called


@respx.mock
async def test_notion_error_response_raises_integration_error():
    respx.post("https://api.notion.com/v1/databases/db-123/query").mock(
        return_value=Response(403, text="Forbidden")
    )
    client = NotionClient(_notion_integration())

    try:
        await client.fetch_documents()
        raise AssertionError("expected IntegrationError")
    except IntegrationError:
        pass


@respx.mock
async def test_notion_requests_carry_the_required_notion_version_header():
    route = respx.post("https://api.notion.com/v1/databases/db-123/query").mock(
        return_value=Response(200, json={"results": [], "has_more": False})
    )
    client = NotionClient(_notion_integration())

    await client.fetch_documents()

    assert route.calls.last.request.headers["Notion-Version"] == "2022-06-28"


def test_google_drive_client_requires_folder_id_or_file_ids():
    integration = _oauth2_integration(base_url="https://www.googleapis.com", provider="google_drive")
    try:
        GoogleDriveClient(integration, session=object())
        raise AssertionError("expected IntegrationError")
    except IntegrationError:
        pass


@respx.mock
async def test_google_drive_fetch_documents_by_folder_id_only_exports_google_docs():
    respx.get("https://www.googleapis.com/drive/v3/files").mock(
        return_value=Response(
            200,
            json={
                "files": [
                    {
                        "id": "doc-1",
                        "name": "Refund Policy",
                        "mimeType": "application/vnd.google-apps.document",
                        "modifiedTime": "2026-01-01T00:00:00.000Z",
                    },
                    {
                        "id": "img-1",
                        "name": "logo.png",
                        "mimeType": "image/png",
                        "modifiedTime": "2026-01-01T00:00:00.000Z",
                    },
                ]
            },
        )
    )
    respx.get("https://www.googleapis.com/drive/v3/files/doc-1/export").mock(
        return_value=Response(200, text="Refunds within 30 days.")
    )
    client = GoogleDriveClient(
        _oauth2_integration(base_url="https://www.googleapis.com", provider="google_drive", folder_id="f1"),
        session=object(),
    )

    documents = await client.fetch_documents()

    # The non-Google-Doc file (logo.png) is silently skipped - see the
    # class docstring's documented v1 limitation, not a bug.
    assert len(documents) == 1
    doc = documents[0]
    assert doc.title == "Refund Policy"
    assert doc.source == "google_drive:doc-1"
    assert doc.version == "2026-01-01T00:00:00.000Z"
    assert doc.text == "Refunds within 30 days."


@respx.mock
async def test_google_drive_fetch_documents_by_explicit_file_ids_skips_folder_listing():
    folder_route = respx.get("https://www.googleapis.com/drive/v3/files")
    respx.get("https://www.googleapis.com/drive/v3/files/doc-2").mock(
        return_value=Response(
            200,
            json={
                "id": "doc-2",
                "name": "Shipping FAQ",
                "mimeType": "application/vnd.google-apps.document",
                "modifiedTime": "2026-02-01T00:00:00.000Z",
            },
        )
    )
    respx.get("https://www.googleapis.com/drive/v3/files/doc-2/export").mock(
        return_value=Response(200, text="Ships in 3-5 days.")
    )
    client = GoogleDriveClient(
        _oauth2_integration(
            base_url="https://www.googleapis.com", provider="google_drive", file_ids=["doc-2"]
        ),
        session=object(),
    )

    documents = await client.fetch_documents()

    assert len(documents) == 1
    assert documents[0].source == "google_drive:doc-2"
    assert not folder_route.called


@respx.mock
async def test_google_drive_error_response_raises_integration_error():
    respx.get("https://www.googleapis.com/drive/v3/files").mock(
        return_value=Response(401, text="Unauthorized")
    )
    client = GoogleDriveClient(
        _oauth2_integration(base_url="https://www.googleapis.com", provider="google_drive", folder_id="f1"),
        session=object(),
    )

    try:
        await client.fetch_documents()
        raise AssertionError("expected IntegrationError")
    except IntegrationError:
        pass


def test_sharepoint_client_requires_drive_id():
    integration = _oauth2_integration(base_url="https://graph.microsoft.com", provider="sharepoint")
    try:
        SharePointClient(integration, session=object())
        raise AssertionError("expected IntegrationError")
    except IntegrationError:
        pass


@respx.mock
async def test_sharepoint_fetch_documents_only_fetches_text_like_files():
    respx.get("https://graph.microsoft.com/v1.0/drives/drive-1/root/children").mock(
        return_value=Response(
            200,
            json={
                "value": [
                    {"id": "item-1", "name": "policy.md", "lastModifiedDateTime": "2026-01-01T00:00:00Z"},
                    {"id": "item-2", "name": "deck.pptx", "lastModifiedDateTime": "2026-01-01T00:00:00Z"},
                ]
            },
        )
    )
    respx.get("https://graph.microsoft.com/v1.0/drives/drive-1/items/item-1/content").mock(
        return_value=Response(200, text="Refunds within 30 days.")
    )
    client = SharePointClient(
        _oauth2_integration(
            base_url="https://graph.microsoft.com", provider="sharepoint", drive_id="drive-1"
        ),
        session=object(),
    )

    documents = await client.fetch_documents()

    # deck.pptx is silently skipped - not a supported text extension, see
    # the class docstring's documented v1 limitation.
    assert len(documents) == 1
    doc = documents[0]
    assert doc.title == "policy.md"
    assert doc.source == "sharepoint:item-1"
    assert doc.version == "2026-01-01T00:00:00Z"
    assert doc.text == "Refunds within 30 days."


@respx.mock
async def test_sharepoint_fetch_documents_by_explicit_file_ids_skips_folder_listing():
    folder_route = respx.get("https://graph.microsoft.com/v1.0/drives/drive-1/root/children")
    respx.get("https://graph.microsoft.com/v1.0/drives/drive-1/items/item-3").mock(
        return_value=Response(
            200, json={"id": "item-3", "name": "faq.txt", "lastModifiedDateTime": "2026-02-01T00:00:00Z"}
        )
    )
    respx.get("https://graph.microsoft.com/v1.0/drives/drive-1/items/item-3/content").mock(
        return_value=Response(200, text="Ships in 3-5 days.")
    )
    client = SharePointClient(
        _oauth2_integration(
            base_url="https://graph.microsoft.com",
            provider="sharepoint",
            drive_id="drive-1",
            file_ids=["item-3"],
        ),
        session=object(),
    )

    documents = await client.fetch_documents()

    assert len(documents) == 1
    assert documents[0].source == "sharepoint:item-3"
    assert not folder_route.called


@respx.mock
async def test_sharepoint_error_response_raises_integration_error():
    respx.get("https://graph.microsoft.com/v1.0/drives/drive-1/root/children").mock(
        return_value=Response(403, text="Forbidden")
    )
    client = SharePointClient(
        _oauth2_integration(
            base_url="https://graph.microsoft.com", provider="sharepoint", drive_id="drive-1"
        ),
        session=object(),
    )

    try:
        await client.fetch_documents()
        raise AssertionError("expected IntegrationError")
    except IntegrationError:
        pass


def test_get_docs_client_dispatches_google_drive_and_sharepoint_with_a_session():
    google_integration = _oauth2_integration(
        base_url="https://www.googleapis.com", provider="google_drive", folder_id="f1"
    )
    sharepoint_integration = _oauth2_integration(
        base_url="https://graph.microsoft.com", provider="sharepoint", drive_id="drive-1"
    )
    session = object()

    assert isinstance(get_docs_client(google_integration, session=session), GoogleDriveClient)
    assert isinstance(get_docs_client(sharepoint_integration, session=session), SharePointClient)
