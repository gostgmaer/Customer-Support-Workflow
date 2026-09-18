"""Staff-facing Knowledge Base API (spec: help-desk-kit-style KB) over the
same `knowledge_documents`/`knowledge_chunks` tables the RAG pipeline
retrieves from during a support conversation (app.rag.ingest /
app.rag.docs_ingest / app.rag.retriever). Browse/search/feedback are
read-only; `POST /upload` (ADMIN only) is the one write path here - it
runs a manually-uploaded file through the exact same
chunk-embed-store pipeline `make seed`/a docs-integration sync uses, so an
uploaded document is immediately both visible in this browse UI *and*
retrievable by the AI in chat (e.g. "what's your return policy?"), not a
separate, disconnected copy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.knowledge import (
    KnowledgeArticleDetail,
    KnowledgeArticleSummary,
    KnowledgeCategorySummary,
    KnowledgeFeedbackRequest,
)
from app.db.session import get_db
from app.domain.exceptions import ValidationError
from app.domain.models import KnowledgeDocument
from app.rag.ingest import ingest_documents
from app.rag.loaders import LoadedDocument, clean_text
from app.repositories.knowledge import KnowledgeDocumentRepository
from app.security.auth import require_staff_role

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])

RequireStaff = Depends(require_staff_role())
RequireAdmin = Depends(require_staff_role("ADMIN"))

_SUMMARY_LENGTH = 180
# A support-doc upload (policy pages, FAQs) has no business being large;
# capping this keeps a mistaken upload (e.g. a PDF renamed to .txt) from
# producing a multi-thousand-chunk embedding job.
_MAX_UPLOAD_BYTES = 2 * 1024 * 1024
_ALLOWED_EXTENSIONS = (".md", ".markdown", ".txt")


def _summary(document: KnowledgeDocument) -> str:
    text = " ".join(document.raw_text.split())
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
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


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
    """Ingests an uploaded `.md`/`.txt` file into the real RAG pipeline
    (chunked, embedded, and upserted into the tenant's vector-store
    namespace) so it is retrievable by the AI in the very next customer
    message, not just readable here. Every upload creates a new, distinct
    document (a unique `source` per call) rather than trying to detect
    "is this an update to an existing article" - that dedupe/version-bump
    semantics exists for automated docs-integration syncs
    (app.rag.docs_ingest), not a one-off manual upload where an admin
    doing it again is a deliberate new document, not an accidental repeat.
    """
    _admin_id, _role, tenant_id = admin

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
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("File must be UTF-8 encoded text") from exc

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
    return _to_detail(stored)
