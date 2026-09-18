"""External document-source clients for RAG ingestion (spec: Phase 9.3,
Google Drive/SharePoint added in Phase 10.4).

Every client returns `app.rag.loaders.LoadedDocument` directly - the
same shape the local markdown loader produces - so a synced page slots
into the exact same `app.rag.ingest.ingest_documents` pipeline a
directory load already uses, no separate ingestion path needed.

Confluence uses `basic` auth (email + API token, identical to this
codebase's existing JIRA client) and returns storage-format XHTML that
needs `app.integrations.html_text.html_to_text` to strip. Notion uses
`bearer` auth (an internal integration token) and returns structured
JSON blocks (no HTML stripping needed) - but Notion's API requires a
fixed `Notion-Version` header on every request, a genuine deviation from
every other client in this codebase, added as a per-request header
rather than a `build_http_client` change since it's Notion-specific, not
a new general auth concept.

Google Drive and SharePoint use `oauth2` auth (spec: Phase 10.4) - the
first OAuth2-backed clients in this codebase, since Confluence/Notion's
static tokens never expire. Both call
`app.integrations.base.ensure_fresh_oauth2_token` before
`build_http_client`, which is why they alone need a `session` passed
into their constructor - Confluence/Notion need no such thing.

Built and tested entirely against fixture data shaped to match each
provider's real, public API documentation - no real Confluence/Notion
workspace, Google Drive folder, or SharePoint site exists yet to verify
a live sync against (see docs/ARCHITECTURE.md's "RAG doc connectors" for
the documented live-verification gap and exactly what to do once one
exists).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import IntegrationError
from app.domain.models import Integration
from app.integrations.base import build_http_client, ensure_fresh_oauth2_token, short_response_body
from app.integrations.html_text import html_to_text
from app.rag.loaders import LoadedDocument

_NOTION_VERSION = "2022-06-28"


class ConfluenceClient:
    """Confluence Cloud REST API v2. `config.space_key` (sync every page
    in a space) or `config.page_ids` (a specific list) - at least one
    required, mirroring the openapi integration type's
    spec_url/spec_inline "at least one source" pattern."""

    def __init__(self, integration: Integration) -> None:
        self._integration = integration
        self._space_key = integration.config.get("space_key")
        self._page_ids: list[str] = integration.config.get("page_ids") or []
        if not self._space_key and not self._page_ids:
            raise IntegrationError(
                f"Confluence integration '{integration.name}' requires config.space_key or config.page_ids"
            )
        self._category = integration.config.get("category", "general")

    async def _resolve_page_ids(self, client: Any) -> list[str]:
        if self._page_ids:
            return self._page_ids
        # Confluence Cloud's v2 API addresses a space by numeric id, not
        # its human-readable key - resolve the key to an id first.
        space_response = await client.get("/wiki/api/v2/spaces", params={"keys": self._space_key})
        if space_response.status_code >= 400:
            raise IntegrationError(
                f"Confluence space lookup failed ({space_response.status_code}): "
                f"{short_response_body(space_response.text)}"
            )
        results = space_response.json().get("results", [])
        if not results:
            raise IntegrationError(f"Confluence space '{self._space_key}' not found")
        space_id = results[0]["id"]

        page_ids: list[str] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            pages_response = await client.get(f"/wiki/api/v2/spaces/{space_id}/pages", params=params)
            if pages_response.status_code >= 400:
                raise IntegrationError(
                    f"Confluence page listing failed ({pages_response.status_code}): "
                    f"{short_response_body(pages_response.text)}"
                )
            body = pages_response.json()
            page_ids.extend(p["id"] for p in body.get("results", []))
            cursor = (body.get("_links", {}) or {}).get("next")
            if not cursor:
                break
        return page_ids

    async def fetch_documents(self) -> list[LoadedDocument]:
        documents: list[LoadedDocument] = []
        async with build_http_client(self._integration) as client:
            page_ids = await self._resolve_page_ids(client)
            for page_id in page_ids:
                response = await client.get(
                    f"/wiki/api/v2/pages/{page_id}", params={"body-format": "storage"}
                )
                if response.status_code >= 400:
                    raise IntegrationError(
                        f"Confluence page fetch failed ({response.status_code}): "
                        f"{short_response_body(response.text)}"
                    )
                page = response.json()
                storage_body = (page.get("body", {}).get("storage", {}) or {}).get("value", "")
                version_number = str((page.get("version", {}) or {}).get("number", "1"))
                documents.append(
                    LoadedDocument(
                        title=page.get("title", page_id),
                        source=f"confluence:{page_id}",
                        category=self._category,
                        version=version_number,
                        effective_date=datetime.now(UTC),
                        expiration_date=None,
                        language="en",
                        text=html_to_text(storage_body),
                    )
                )
        return documents


class NotionClient:
    """Notion API. `config.database_id` (sync every page in a database)
    or `config.page_ids` (a specific list) - at least one required."""

    def __init__(self, integration: Integration) -> None:
        self._integration = integration
        self._database_id = integration.config.get("database_id")
        self._page_ids: list[str] = integration.config.get("page_ids") or []
        if not self._database_id and not self._page_ids:
            raise IntegrationError(
                f"Notion integration '{integration.name}' requires config.database_id or config.page_ids"
            )
        self._category = integration.config.get("category", "general")

    def _headers(self) -> dict[str, str]:
        return {"Notion-Version": _NOTION_VERSION}

    async def _resolve_page_ids(self, client: Any) -> list[str]:
        if self._page_ids:
            return self._page_ids
        page_ids: list[str] = []
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {}
            if cursor:
                body["start_cursor"] = cursor
            response = await client.post(
                f"/v1/databases/{self._database_id}/query", json=body, headers=self._headers()
            )
            if response.status_code >= 400:
                raise IntegrationError(
                    f"Notion database query failed ({response.status_code}): "
                    f"{short_response_body(response.text)}"
                )
            data = response.json()
            page_ids.extend(p["id"] for p in data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return page_ids

    @staticmethod
    def _extract_title(page: dict[str, Any]) -> str:
        for prop in page.get("properties", {}).values():
            if prop.get("type") == "title":
                title_parts = prop.get("title", [])
                text = "".join(t.get("plain_text", "") for t in title_parts)
                if text:
                    return text
        return page.get("id", "Untitled")

    @staticmethod
    def _extract_block_text(blocks: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for block in blocks:
            block_type = block.get("type", "")
            content = block.get(block_type, {}) if isinstance(block.get(block_type), dict) else {}
            rich_text = content.get("rich_text", [])
            text = "".join(t.get("plain_text", "") for t in rich_text)
            if text:
                lines.append(text)
        return "\n\n".join(lines)

    async def _fetch_all_blocks(self, client: Any, page_id: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params = {"start_cursor": cursor} if cursor else {}
            response = await client.get(
                f"/v1/blocks/{page_id}/children", params=params, headers=self._headers()
            )
            if response.status_code >= 400:
                raise IntegrationError(
                    f"Notion block fetch failed ({response.status_code}): "
                    f"{short_response_body(response.text)}"
                )
            data = response.json()
            blocks.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return blocks

    async def fetch_documents(self) -> list[LoadedDocument]:
        documents: list[LoadedDocument] = []
        async with build_http_client(self._integration) as client:
            page_ids = await self._resolve_page_ids(client)
            for page_id in page_ids:
                page_response = await client.get(f"/v1/pages/{page_id}", headers=self._headers())
                if page_response.status_code >= 400:
                    raise IntegrationError(
                        f"Notion page fetch failed ({page_response.status_code}): "
                        f"{short_response_body(page_response.text)}"
                    )
                page = page_response.json()
                blocks = await self._fetch_all_blocks(client, page_id)
                # last_edited_time changing is Notion's own signal that
                # content changed - there's no numeric page version the
                # way Confluence has one, but this serves the identical
                # role in ingest_documents's update_on_version_change check.
                version = page.get("last_edited_time", "")
                documents.append(
                    LoadedDocument(
                        title=self._extract_title(page),
                        source=f"notion:{page_id}",
                        category=self._category,
                        version=version,
                        effective_date=datetime.now(UTC),
                        expiration_date=None,
                        language="en",
                        text=self._extract_block_text(blocks),
                    )
                )
        return documents


class GoogleDriveClient:
    """Google Drive (spec: Phase 10.4). `config.folder_id` (sync every
    Google Doc in a folder) or `config.file_ids` (a specific list) - at
    least one required, mirroring every other docs provider's "at least
    one source" pattern. Only Google Docs (exported as plain text via
    Drive's `files.export`) are fetched - arbitrary binary files (PDFs,
    images, spreadsheets) are an accepted v1 limitation, not attempted,
    matching this codebase's own precedent of documenting a deliberate
    scope boundary rather than silently mishandling unsupported content."""

    def __init__(self, integration: Integration, session: AsyncSession) -> None:
        self._integration = integration
        self._session = session
        self._folder_id = integration.config.get("folder_id")
        self._file_ids: list[str] = integration.config.get("file_ids") or []
        if not self._folder_id and not self._file_ids:
            raise IntegrationError(
                f"Google Drive integration '{integration.name}' requires config.folder_id or config.file_ids"
            )
        self._category = integration.config.get("category", "general")

    async def _list_files(self, client: Any) -> list[dict[str, Any]]:
        if self._file_ids:
            files: list[dict[str, Any]] = []
            for file_id in self._file_ids:
                response = await client.get(
                    f"/drive/v3/files/{file_id}", params={"fields": "id,name,mimeType,modifiedTime"}
                )
                if response.status_code >= 400:
                    raise IntegrationError(
                        f"Google Drive file lookup failed ({response.status_code}): "
                        f"{short_response_body(response.text)}"
                    )
                files.append(response.json())
            return files

        files = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "q": f"'{self._folder_id}' in parents and trashed = false",
                "fields": "nextPageToken, files(id,name,mimeType,modifiedTime)",
            }
            if page_token:
                params["pageToken"] = page_token
            response = await client.get("/drive/v3/files", params=params)
            if response.status_code >= 400:
                raise IntegrationError(
                    f"Google Drive folder listing failed ({response.status_code}): "
                    f"{short_response_body(response.text)}"
                )
            body = response.json()
            files.extend(body.get("files", []))
            page_token = body.get("nextPageToken")
            if not page_token:
                break
        return files

    async def fetch_documents(self) -> list[LoadedDocument]:
        await ensure_fresh_oauth2_token(self._integration, self._session)
        documents: list[LoadedDocument] = []
        async with build_http_client(self._integration) as client:
            files = await self._list_files(client)
            for file in files:
                if file.get("mimeType") != "application/vnd.google-apps.document":
                    continue  # not a Google Doc - see class docstring's documented limitation
                response = await client.get(
                    f"/drive/v3/files/{file['id']}/export", params={"mimeType": "text/plain"}
                )
                if response.status_code >= 400:
                    raise IntegrationError(
                        f"Google Drive export failed ({response.status_code}): "
                        f"{short_response_body(response.text)}"
                    )
                documents.append(
                    LoadedDocument(
                        title=file.get("name", file["id"]),
                        source=f"google_drive:{file['id']}",
                        category=self._category,
                        version=file.get("modifiedTime", ""),
                        effective_date=datetime.now(UTC),
                        expiration_date=None,
                        language="en",
                        text=response.text,
                    )
                )
        return documents


class SharePointClient:
    """SharePoint via Microsoft Graph (spec: Phase 10.4). `config.drive_id`
    (the document library's drive id) is required; `config.folder_path`
    (default root) scopes to one folder, or `config.file_ids` for a
    specific list. Only plain-text-ish files (`.txt`/`.md`) are fetched
    as content - Word/PDF/Excel documents need a real format converter
    this v1 doesn't attempt, an accepted limitation matching Google
    Drive's own Google-Docs-only scope above."""

    _TEXT_EXTENSIONS = (".txt", ".md")

    def __init__(self, integration: Integration, session: AsyncSession) -> None:
        self._integration = integration
        self._session = session
        self._drive_id = integration.config.get("drive_id")
        self._folder_path = integration.config.get("folder_path", "")
        self._file_ids: list[str] = integration.config.get("file_ids") or []
        if not self._drive_id:
            raise IntegrationError(f"SharePoint integration '{integration.name}' requires config.drive_id")
        self._category = integration.config.get("category", "general")

    async def _list_items(self, client: Any) -> list[dict[str, Any]]:
        if self._file_ids:
            items: list[dict[str, Any]] = []
            for item_id in self._file_ids:
                response = await client.get(f"/v1.0/drives/{self._drive_id}/items/{item_id}")
                if response.status_code >= 400:
                    raise IntegrationError(
                        f"SharePoint item lookup failed ({response.status_code}): "
                        f"{short_response_body(response.text)}"
                    )
                items.append(response.json())
            return items

        path_segment = f":/{self._folder_path}:" if self._folder_path else ""
        items = []
        url: str | None = f"/v1.0/drives/{self._drive_id}/root{path_segment}/children"
        while url:
            response = await client.get(url)
            if response.status_code >= 400:
                raise IntegrationError(
                    f"SharePoint folder listing failed ({response.status_code}): "
                    f"{short_response_body(response.text)}"
                )
            body = response.json()
            items.extend(body.get("value", []))
            next_link = body.get("@odata.nextLink")
            # Graph returns a full absolute URL for pagination - build_http_client's
            # base_url is https://graph.microsoft.com, so strip that prefix.
            url = next_link.replace("https://graph.microsoft.com", "") if next_link else None
        return items

    async def fetch_documents(self) -> list[LoadedDocument]:
        await ensure_fresh_oauth2_token(self._integration, self._session)
        documents: list[LoadedDocument] = []
        async with build_http_client(self._integration) as client:
            items = await self._list_items(client)
            for item in items:
                name = item.get("name", "")
                if "folder" in item or not name.lower().endswith(self._TEXT_EXTENSIONS):
                    continue  # a subfolder, or a format this v1 doesn't convert - see class docstring
                item_id = item["id"]
                response = await client.get(f"/v1.0/drives/{self._drive_id}/items/{item_id}/content")
                if response.status_code >= 400:
                    raise IntegrationError(
                        f"SharePoint content fetch failed ({response.status_code}): "
                        f"{short_response_body(response.text)}"
                    )
                documents.append(
                    LoadedDocument(
                        title=name,
                        source=f"sharepoint:{item_id}",
                        category=self._category,
                        version=item.get("lastModifiedDateTime", ""),
                        effective_date=datetime.now(UTC),
                        expiration_date=None,
                        language="en",
                        text=response.text,
                    )
                )
        return documents


def get_docs_client(
    integration: Integration, *, session: AsyncSession | None = None
) -> ConfluenceClient | NotionClient | GoogleDriveClient | SharePointClient:
    provider = integration.config.get("provider")
    if provider == "confluence":
        return ConfluenceClient(integration)
    if provider == "notion":
        return NotionClient(integration)
    if provider == "google_drive":
        if session is None:
            raise IntegrationError("Google Drive docs integrations require a database session")
        return GoogleDriveClient(integration, session)
    if provider == "sharepoint":
        if session is None:
            raise IntegrationError("SharePoint docs integrations require a database session")
        return SharePointClient(integration, session)
    raise IntegrationError(
        f"Docs integration '{integration.name}' has an unknown or missing config.provider "
        f"'{provider}' - expected 'confluence', 'notion', 'google_drive', or 'sharepoint'"
    )
