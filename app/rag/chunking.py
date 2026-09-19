"""Chunking + metadata enrichment (spec §8; Phase 11 Tier 2: structure-aware
chunking via LangChain, replacing the previous blank-line-only splitter).

`MarkdownHeaderTextSplitter` splits on `#`/`##`/`###` headings first,
preserving each section's heading path and keeping a block like a GFM
table intact within its section (verified against the real installed
`langchain-text-splitters` behavior, not assumed - see the audit in
Phase 11's plan). Any section still over `chunk_size` is further split by
`RecursiveCharacterTextSplitter`. A document with no headings at all (a
plain seed .txt, or already-short text) yields exactly one section with
an empty `section_path`, so this never regresses the flat-text case the
old splitter handled.

`token_count` is an approximation (chars / 4), not a real tokenizer call:
`tiktoken` is not an actual dependency of this project (verified - it
only appears in this dev machine's shared venv as a transitive dependency
of an unrelated project, not of anything in pyproject.toml), and adding a
new heavy dependency solely for an estimate used in metadata/observability
isn't justified.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from app.rag.loaders import LoadedDocument

# Bumped when chunking logic changes materially enough that previously
# stored chunks should be considered stale/re-ingested - stamped onto
# every chunk's metadata (spec: Phase 11 Tier 2.2 versioning).
CHUNKING_VERSION = "v2"

_HEADERS_TO_SPLIT_ON = [("#", "h1"), ("##", "h2"), ("###", "h3")]


@dataclass
class DocumentChunk:
    text: str
    chunk_index: int
    metadata: dict = field(default_factory=dict)


def _content_hash(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()


def chunk_text(
    text: str, *, max_chars: int = 800, overlap: int = 100
) -> list[tuple[str, list[str]]]:
    """Returns (chunk_text, section_path) pairs - `section_path` is the
    list of heading strings (h1, then h2, then h3 if present) the chunk
    fell under, empty for a document/section with no markdown headings.
    """
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=_HEADERS_TO_SPLIT_ON, strip_headers=False
    )
    sub_splitter = RecursiveCharacterTextSplitter(chunk_size=max_chars, chunk_overlap=overlap)

    sections = header_splitter.split_text(text)
    results: list[tuple[str, list[str]]] = []
    for section in sections:
        section_path = [v for v in section.metadata.values() if v]
        content = section.page_content.strip()
        if not content:
            continue
        if len(content) <= max_chars:
            results.append((content, section_path))
        else:
            for sub in sub_splitter.split_text(content):
                if sub.strip():
                    results.append((sub, section_path))
    return results


def build_chunks(document: LoadedDocument, *, document_id: str) -> list[DocumentChunk]:
    from app.config import get_settings

    settings = get_settings()
    chunks: list[DocumentChunk] = []
    for i, (text, section_path) in enumerate(
        chunk_text(document.text, max_chars=settings.chunk_size, overlap=settings.chunk_overlap)
    ):
        metadata = {
            "document_id": document_id,
            "title": document.title,
            "source": document.source,
            "category": document.category,
            "version": document.version,
            "effective_date": document.effective_date.isoformat(),
            "expiration_date": document.expiration_date.isoformat() if document.expiration_date else None,
            "language": document.language,
            "content_hash": _content_hash(text),
            "token_count": max(1, len(text) // 4),
            "section_path": section_path,
            "chunking_version": CHUNKING_VERSION,
        }
        chunks.append(DocumentChunk(text=text, chunk_index=i, metadata=metadata))
    return chunks
