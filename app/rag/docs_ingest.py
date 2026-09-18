"""Syncs an external `"docs"` integration (Confluence/Notion - spec:
Phase 9.3) into the knowledge base, reusing the exact same
dedupe/chunk/embed/upsert pipeline `ingest_knowledge_directory` uses for
local markdown files - see `app.rag.ingest.ingest_documents`.

No scheduler/cron exists anywhere in this codebase, so this is triggered
manually (`POST /api/v1/admin/integrations/{id}/sync`), not on a
schedule - a deliberate MVP scope, matching this project's own
established practice of not introducing new infrastructure (a job
queue, a cron runner) for a feature that doesn't yet need one.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import DEFAULT_TENANT_ID
from app.domain.models import Integration
from app.integrations.docs_connector import get_docs_client
from app.rag.embeddings import Embedder, get_embedder
from app.rag.ingest import ingest_documents
from app.repositories.vector_store import VectorRepository, get_vector_store


async def sync_docs_integration(
    integration: Integration,
    session: AsyncSession,
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
    embedder: Embedder | None = None,
    vector_store: VectorRepository | None = None,
) -> int:
    """Fetches every document `integration` currently exposes and ingests
    it, updating any document whose `version` (Confluence: numeric page
    version; Notion: `last_edited_time`) has changed since the last sync
    - see `ingest_documents`'s `update_on_version_change` for why this
    differs from the local-file loader's plain skip-if-exists behavior:
    a live external source can change silently between syncs."""
    client = get_docs_client(integration, session=session)
    documents = await client.fetch_documents()
    return await ingest_documents(
        documents,
        session,
        tenant_id=tenant_id,
        embedder=embedder or get_embedder(),
        vector_store=vector_store or get_vector_store(session),
        update_on_version_change=True,
    )
