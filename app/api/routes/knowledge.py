"""Knowledge Base API (spec: help-desk-kit-style KB) over the same
`knowledge_documents`/`knowledge_chunks` tables the RAG pipeline retrieves
from during a support conversation (app.rag.ingest / app.rag.docs_ingest /
app.rag.retriever). Browse/search/feedback/upload are staff-only
(`RequireStaff`/`RequireAdmin`); `POST /ask` is the one route open to
customers too (`RequireAnyUser`) - it's a stateless RAG Q&A chat shared by
both portals, not a replacement for the customer support ticket flow
(app.api.routes.support), which still owns tool calls/escalation/tickets.
`POST /upload` (ADMIN only) runs a manually-uploaded file through the
exact same chunk-embed-store pipeline `make seed`/a docs-integration sync
uses, so an uploaded document is immediately both visible in the browse UI
*and* retrievable by `/ask` and the support chat, not a separate,
disconnected copy.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.resolution import draft_response
from app.api.schemas.knowledge import (
    KnowledgeArticleDetail,
    KnowledgeArticleSummary,
    KnowledgeAskRequest,
    KnowledgeAskResponse,
    KnowledgeCategorySummary,
    KnowledgeFeedbackRequest,
)
from app.config import get_settings
from app.config.dynamic_settings import get_effective_settings
from app.db.session import get_db
from app.domain.exceptions import ValidationError
from app.domain.models import KnowledgeDocument
from app.llm.router import TenantScopedLLMRouter, get_llm_router
from app.observability.logging import get_logger
from app.rag.file_extractors import SUPPORTED_UPLOAD_EXTENSIONS, FileExtractionError, extract_text
from app.rag.ingest import ingest_documents
from app.rag.loaders import LoadedDocument, clean_text
from app.rag.retriever import Retriever
from app.repositories.knowledge import KnowledgeDocumentRepository
from app.repositories.vector_store import get_vector_store
from app.security.auth import get_current_user, require_staff_role
from app.storage.base import FileNotFoundInStorage
from app.storage.factory import StorageNotConfiguredError, get_file_storage

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])

RequireStaff = Depends(require_staff_role())
RequireAdmin = Depends(require_staff_role("ADMIN"))
RequireAnyUser = Depends(get_current_user)

_NOT_FOUND_ANSWER = (
    "I couldn't find anything in the knowledge base about that. Try rephrasing your "
    "question, or a team member can help if you're not sure."
)

_SUMMARY_LENGTH = 180
# A support-doc upload (policy pages, FAQs) has no business being large;
# capping this keeps a mistaken upload (e.g. a scanned-image PDF) from
# producing a multi-thousand-chunk embedding job. Bigger than the old
# text-only limit since real policy PDFs/docx files run heavier than
# equivalent plain text - still bounded, not unlimited.
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_ALLOWED_EXTENSIONS = SUPPORTED_UPLOAD_EXTENSIONS


# A .docx upload's extracted text is real markdown (app.rag.file_extractors -
# heading "#" prefixes, GFM pipe tables) - the card/list previews strip
# that syntax rather than showing "# Return Policy | Item | Window" as
# literal characters. The full article view (ArticleDetail.tsx, frontend)
# still renders `raw_text` as actual markdown - only this short preview
# needs plain text.
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,9}\s*", flags=re.MULTILINE)
_MARKDOWN_TABLE_SEPARATOR_RE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?$", flags=re.MULTILINE)
_MARKDOWN_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|_)")


def _strip_markdown_for_preview(text: str) -> str:
    text = _MARKDOWN_TABLE_SEPARATOR_RE.sub(" ", text)
    text = _MARKDOWN_HEADING_RE.sub("", text)
    text = _MARKDOWN_EMPHASIS_RE.sub("", text)
    return text.replace("|", " ")


def _summary(document: KnowledgeDocument) -> str:
    text = " ".join(_strip_markdown_for_preview(document.raw_text).split())
    if len(text) <= _SUMMARY_LENGTH:
        return text
    return text[:_SUMMARY_LENGTH].rsplit(" ", 1)[0] + "..."


def _to_summary(document: KnowledgeDocument) -> dict:
    return {
        "id": document.id,
        "title": document.title,
        "category": document.category,
        "summary": _summary(document),
        "view_count": document.view_count,
        "helpful_percent": KnowledgeDocumentRepository.helpful_percent(document),
        "updated_at": document.updated_at.isoformat(),
    }


def _to_detail(document: KnowledgeDocument) -> dict:
    return {
        "id": document.id,
        "title": document.title,
        "category": document.category,
        "source": document.source,
        "version": document.version,
        "raw_text": document.raw_text,
        "view_count": document.view_count,
        "helpful_yes_count": document.helpful_yes_count,
        "helpful_no_count": document.helpful_no_count,
        "helpful_percent": KnowledgeDocumentRepository.helpful_percent(document),
        "created_by": document.created_by,
        "has_original_file": document.storage_key is not None,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


def _original_filename(document: KnowledgeDocument) -> str:
    # source is always "upload:<uuid>:<filename>" for an uploaded document
    # (see upload_knowledge_document below) - fall back to the title if
    # this is ever called on something that doesn't match that shape.
    parts = document.source.split(":", 2)
    if len(parts) == 3 and parts[0] == "upload":
        return parts[2]
    return document.title


@router.get("/categories", response_model=list[KnowledgeCategorySummary])
async def list_categories(
    session: AsyncSession = Depends(get_db), staff: tuple[str, str, str] = RequireStaff
) -> list[dict]:
    _staff_id, _role, tenant_id = staff
    rows = await KnowledgeDocumentRepository(session, tenant_id).list_categories()
    return [{"category": category, "article_count": count} for category, count in rows]


@router.get("/articles", response_model=list[KnowledgeArticleSummary])
async def list_articles(
    category: str | None = None,
    q: str | None = None,
    sort: str = Query(default="recent", pattern="^(recent|popular)$"),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    staff: tuple[str, str, str] = RequireStaff,
) -> list[dict]:
    _staff_id, _role, tenant_id = staff
    repo = KnowledgeDocumentRepository(session, tenant_id)
    if sort == "popular" and not category and not q:
        documents = await repo.popular(limit=limit)
    else:
        documents = await repo.search(category=category, q=q, limit=limit)
    return [_to_summary(d) for d in documents]


@router.get("/articles/{article_id}", response_model=KnowledgeArticleDetail)
async def get_article(
    article_id: str,
    session: AsyncSession = Depends(get_db),
    staff: tuple[str, str, str] = RequireStaff,
) -> dict:
    _staff_id, _role, tenant_id = staff
    repo = KnowledgeDocumentRepository(session, tenant_id)
    document = await repo.get(article_id)
    if document is None:
        raise ValidationError(f"Knowledge article {article_id} not found")
    await repo.increment_view(document)
    await session.commit()
    return _to_detail(document)


@router.get("/articles/{article_id}/related", response_model=list[KnowledgeArticleSummary])
async def get_related_articles(
    article_id: str,
    session: AsyncSession = Depends(get_db),
    staff: tuple[str, str, str] = RequireStaff,
) -> list[dict]:
    _staff_id, _role, tenant_id = staff
    repo = KnowledgeDocumentRepository(session, tenant_id)
    document = await repo.get(article_id)
    if document is None:
        raise ValidationError(f"Knowledge article {article_id} not found")
    related = await repo.related(document)
    return [_to_summary(d) for d in related]


@router.post("/articles/{article_id}/feedback", response_model=KnowledgeArticleDetail)
async def submit_article_feedback(
    article_id: str,
    body: KnowledgeFeedbackRequest,
    session: AsyncSession = Depends(get_db),
    staff: tuple[str, str, str] = RequireStaff,
) -> dict:
    _staff_id, _role, tenant_id = staff
    repo = KnowledgeDocumentRepository(session, tenant_id)
    document = await repo.get(article_id)
    if document is None:
        raise ValidationError(f"Knowledge article {article_id} not found")
    await repo.record_feedback(document, helpful=body.helpful)
    await session.commit()
    return _to_detail(document)


@router.post("/upload", response_model=KnowledgeArticleDetail, status_code=201)
async def upload_knowledge_document(
    title: str = Form(...),
    category: str = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
    admin: tuple[str, str, str] = RequireAdmin,
) -> dict:
    """Ingests an uploaded `.md`/`.txt`/`.pdf`/`.docx` file (text extracted
    via app.rag.file_extractors) into the real RAG pipeline (chunked,
    embedded, and upserted into the tenant's vector-store namespace) so it
    is retrievable by the AI in the very next customer message, not just
    readable here. Every upload creates a new, distinct document (a
    unique `source` per call) rather than trying to detect
    "is this an update to an existing article" - that dedupe/version-bump
    semantics exists for automated docs-integration syncs
    (app.rag.docs_ingest), not a one-off manual upload where an admin
    doing it again is a deliberate new document, not an accidental repeat.
    """
    admin_id, _role, tenant_id = admin

    filename = file.filename or "upload.txt"
    if not filename.lower().endswith(_ALLOWED_EXTENSIONS):
        raise ValidationError(
            f"Unsupported file type - only {', '.join(_ALLOWED_EXTENSIONS)} are accepted"
        )

    raw = await file.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise ValidationError(f"File exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)}MB upload limit")
    if not raw.strip():
        raise ValidationError("Uploaded file is empty")

    try:
        text = extract_text(filename, raw)
    except FileExtractionError as exc:
        raise ValidationError(str(exc)) from exc

    title = title.strip()
    category = category.strip()
    if not title:
        raise ValidationError("title is required")
    if not category:
        raise ValidationError("category is required")

    now = datetime.now(UTC)
    document = LoadedDocument(
        title=title,
        source=f"upload:{uuid4().hex[:8]}:{filename}",
        category=category,
        version="1.0",
        effective_date=now,
        expiration_date=None,
        language="en",
        text=clean_text(text),
    )
    await ingest_documents([document], session, tenant_id=tenant_id)

    repo = KnowledgeDocumentRepository(session, tenant_id)
    stored = await repo.get_by_source(document.source)
    if stored is None:
        # source is freshly UUID-suffixed above, so ingest_documents' own
        # dedupe can't have skipped it - fail loudly rather than return a
        # fabricated response if this is ever somehow unreachable.
        raise ValidationError("Upload succeeded but the new article could not be re-read")
    # ingest_documents is shared with make seed/docs-integration sync,
    # neither of which has a human uploader - set separately here rather
    # than threading an optional uploader id through that shared pipeline.
    stored.created_by = admin_id

    # Storing the original file is a best-effort add-on, never a reason to
    # fail an otherwise-successful upload - the article is already fully
    # usable (browsable, RAG-retrievable) from raw_text alone. Skipped
    # silently (info, not warning) when no provider is configured at all,
    # since that's this app's own zero-setup default state, not an error.
    storage_key = f"knowledge/{tenant_id}/{stored.id}/{filename}"
    try:
        storage = get_file_storage()
        await storage.upload(
            storage_key, raw, content_type=file.content_type or "application/octet-stream"
        )
    except StorageNotConfiguredError:
        logger.info("kb_upload_original_file_storage_skipped", document_id=stored.id)
    except Exception:
        logger.warning("kb_upload_original_file_storage_failed", document_id=stored.id, exc_info=True)
    else:
        stored.storage_provider = get_settings().file_storage_provider
        stored.storage_key = storage_key

    await session.commit()
    return _to_detail(stored)


@router.get("/articles/{article_id}/file")
async def download_original_file(
    article_id: str,
    session: AsyncSession = Depends(get_db),
    staff: tuple[str, str, str] = RequireStaff,
) -> Response:
    """Streams back the exact file that was uploaded (not the extracted
    `raw_text`) - reads from whichever provider that specific document's
    file actually lives on (`document.storage_provider`), which may not
    be the currently-configured default if an operator has since switched
    providers (see scripts/storage/migrate_file_storage.py)."""
    _staff_id, _role, tenant_id = staff
    repo = KnowledgeDocumentRepository(session, tenant_id)
    document = await repo.get(article_id)
    if document is None:
        raise ValidationError(f"Knowledge article {article_id} not found")
    if document.storage_key is None:
        raise ValidationError("No original file was stored for this article")

    storage = get_file_storage(document.storage_provider)
    try:
        data = await storage.download(document.storage_key)
    except FileNotFoundInStorage as exc:
        raise ValidationError("The original file could not be found in storage") from exc

    filename = _original_filename(document)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/ask", response_model=KnowledgeAskResponse)
async def ask_knowledge_base(
    body: KnowledgeAskRequest,
    session: AsyncSession = Depends(get_db),
    user: tuple[str, str, str] = RequireAnyUser,
) -> dict:
    """Stateless RAG Q&A: retrieves against the same tenant-scoped vector
    index the support chat uses (app.workflow.nodes.route_nodes.knowledge_search_node),
    then drafts an answer strictly from what was retrieved via the same
    `draft_response` helper the support workflow itself uses for its
    resolution responses - never a bare LLM call with no grounding. Open
    to both customers and staff (RequireAnyUser); creates no ticket,
    conversation, or any other record - purely an ephemeral lookup.
    """
    _user_id, _scope, tenant_id = user
    question = body.question.strip()
    if not question:
        raise ValidationError("question is required")

    effective = await get_effective_settings(session, tenant_id)
    settings = get_settings()
    vector_store = get_vector_store(session if settings.vector_backend == "pgvector" else None)
    docs = await Retriever(vector_store).retrieve(
        question, tenant_id=tenant_id, min_score=effective.confidence_retrieval
    )

    if not docs:
        return {"answer": _NOT_FOUND_ANSWER, "grounded": False, "sources": []}

    llm_router = TenantScopedLLMRouter(
        get_llm_router(),
        mock_llm=effective.mock_llm,
        default_provider=effective.default_llm_provider,
        fallback_provider=effective.fallback_llm_provider,
    )
    llm = llm_router.get_model("knowledge_qa")
    facts = [f"[{d.title}] {d.text}" for d in docs]
    answer = await draft_response(llm, message=question, facts=facts)

    seen_ids: set[str] = set()
    sources = []
    for d in docs:
        if d.document_id in seen_ids:
            continue
        seen_ids.add(d.document_id)
        sources.append({"id": d.document_id, "title": d.title, "category": d.category})

    return {"answer": answer, "grounded": True, "sources": sources}
