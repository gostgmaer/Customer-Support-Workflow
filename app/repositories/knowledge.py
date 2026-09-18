"""Read/engagement repository for the staff-facing Knowledge Base browse
UI (spec: help-desk-kit-style KB). Ingestion (app.rag.ingest / docs_ingest)
writes KnowledgeDocument rows directly - this repository only reads them
back and tracks view/helpful counters, it never creates or chunks documents.
"""

from __future__ import annotations

from sqlalchemy import func, or_, select, update

from app.domain.models import KnowledgeDocument
from app.repositories.base import TenantScopedRepository


class KnowledgeDocumentRepository(TenantScopedRepository):
    async def list_categories(self) -> list[tuple[str, int]]:
        stmt = self._scope(
            select(KnowledgeDocument.category, func.count().label("count")).group_by(
                KnowledgeDocument.category
            ),
            KnowledgeDocument,
        ).order_by(KnowledgeDocument.category)
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def search(
        self, *, category: str | None = None, q: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[KnowledgeDocument]:
        stmt = self._scope(select(KnowledgeDocument), KnowledgeDocument)
        if category:
            stmt = stmt.where(KnowledgeDocument.category == category)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(KnowledgeDocument.title.ilike(like), KnowledgeDocument.raw_text.ilike(like))
            )
        stmt = stmt.order_by(KnowledgeDocument.updated_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def popular(self, *, limit: int = 4) -> list[KnowledgeDocument]:
        stmt = self._scope(select(KnowledgeDocument), KnowledgeDocument)
        stmt = stmt.order_by(KnowledgeDocument.view_count.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def recent(self, *, limit: int = 5) -> list[KnowledgeDocument]:
        stmt = self._scope(select(KnowledgeDocument), KnowledgeDocument)
        stmt = stmt.order_by(KnowledgeDocument.updated_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, document_id: str) -> KnowledgeDocument | None:
        stmt = self._scope(
            select(KnowledgeDocument).where(KnowledgeDocument.id == document_id), KnowledgeDocument
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_source(self, source: str) -> KnowledgeDocument | None:
        """`(tenant_id, source)` is unique enough in practice for this
        lookup's one caller (re-reading a just-uploaded document by its
        freshly UUID-suffixed source) - source isn't a DB-level unique
        constraint, so this takes the most recently updated match."""
        stmt = self._scope(
            select(KnowledgeDocument).where(KnowledgeDocument.source == source), KnowledgeDocument
        ).order_by(KnowledgeDocument.updated_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def related(self, document: KnowledgeDocument, *, limit: int = 3) -> list[KnowledgeDocument]:
        stmt = self._scope(
            select(KnowledgeDocument).where(
                KnowledgeDocument.category == document.category,
                KnowledgeDocument.id != document.id,
            ),
            KnowledgeDocument,
        ).order_by(KnowledgeDocument.view_count.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def increment_view(self, document: KnowledgeDocument) -> None:
        """Atomic `SET view_count = view_count + 1` via a Core UPDATE, with
        `updated_at` explicitly pinned to its own column expression.

        A plain ORM attribute mutation (`document.view_count += 1`) still
        makes the row "dirty," and TimestampMixin's `onupdate=utcnow` fires
        unconditionally for ANY dirty row unless the column is given an
        explicit value in the same statement - so it would otherwise bump
        `updated_at` on every article view, making "recently updated"
        (sorted by `updated_at`) drift just from reads, not edits. Verified
        live against the real Postgres backend that this explicit-value
        form is what actually suppresses it (a same-value ORM attribute
        re-assignment does not).
        """
        await self.session.execute(
            update(KnowledgeDocument)
            .where(KnowledgeDocument.id == document.id)
            .values(view_count=KnowledgeDocument.view_count + 1, updated_at=KnowledgeDocument.updated_at)
        )
        await self.session.flush()
        await self.session.refresh(document, attribute_names=["view_count"])

    async def record_feedback(self, document: KnowledgeDocument, *, helpful: bool) -> None:
        """See increment_view's docstring for why `updated_at` is pinned."""
        column = KnowledgeDocument.helpful_yes_count if helpful else KnowledgeDocument.helpful_no_count
        await self.session.execute(
            update(KnowledgeDocument)
            .where(KnowledgeDocument.id == document.id)
            .values({column: column + 1, KnowledgeDocument.updated_at: KnowledgeDocument.updated_at})
        )
        await self.session.flush()
        await self.session.refresh(document, attribute_names=["helpful_yes_count", "helpful_no_count"])

    @staticmethod
    def helpful_percent(document: KnowledgeDocument) -> int | None:
        total = document.helpful_yes_count + document.helpful_no_count
        if total == 0:
            return None
        return round(document.helpful_yes_count * 100 / total)
