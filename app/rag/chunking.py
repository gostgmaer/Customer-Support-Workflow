"""Chunking + metadata enrichment (spec §8)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.rag.loaders import LoadedDocument


@dataclass
class DocumentChunk:
    text: str
    chunk_index: int
    metadata: dict = field(default_factory=dict)


def chunk_text(text: str, *, max_chars: int = 800, overlap: int = 100) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= max_chars:
            current = f"{current}\n\n{paragraph}" if current else paragraph
        else:
            if current:
                chunks.append(current)
            if len(paragraph) > max_chars:
                for start in range(0, len(paragraph), max_chars - overlap):
                    chunks.append(paragraph[start : start + max_chars])
                current = ""
            else:
                current = paragraph
    if current:
        chunks.append(current)
    return chunks


def build_chunks(document: LoadedDocument, *, document_id: str) -> list[DocumentChunk]:
    metadata = {
        "document_id": document_id,
        "title": document.title,
        "source": document.source,
        "category": document.category,
        "version": document.version,
        "effective_date": document.effective_date.isoformat(),
        "expiration_date": document.expiration_date.isoformat() if document.expiration_date else None,
        "language": document.language,
    }
    return [
        DocumentChunk(text=text, chunk_index=i, metadata=metadata)
        for i, text in enumerate(chunk_text(document.text))
    ]
