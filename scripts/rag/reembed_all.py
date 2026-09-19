"""One-time re-embed of every existing KnowledgeChunk against the
currently-configured embedder (spec: Phase 11 Tier 1.1 - real embeddings
via LangChain). Real embeddings are not compatible with the old
HashingEmbedder's hash-based vectors (a different vector space entirely),
so cutting over (MOCK_LLM=false + GOOGLE_API_KEY set, see
app.rag.embeddings.get_embedder) requires re-embedding the existing
corpus once - this script does that, reusing the exact same
chunk-fetch/embed/upsert logic app.main's own startup warm-up uses for
the in-memory backend (app.rag.ingest.warm_vector_index_from_db), just
invoked explicitly with progress output rather than silently at boot.

Every chunk, across every tenant (each stays in its own vector-store
namespace - see knowledge_namespace), is re-embedded and its
embedding_model/embedding_version metadata updated to match. Existing
vector-store rows are overwritten in place (upsert), not duplicated.

Usage:
    python scripts/rag/reembed_all.py

Run this once, right after setting MOCK_LLM=false + GOOGLE_API_KEY (or
after changing EMBEDDING_MODEL/VECTOR_DIMENSIONS) - until it runs, the
vector store still holds vectors from whichever embedder produced them
originally, and searches against a newly-configured embedder's queries
will not match them correctly.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import get_settings  # noqa: E402
from app.db.session import get_sessionmaker, init_models  # noqa: E402
from app.rag.embeddings import get_embedder  # noqa: E402
from app.rag.ingest import warm_vector_index_from_db  # noqa: E402
from app.repositories.vector_store import get_vector_store  # noqa: E402


async def reembed_all() -> None:
    settings = get_settings()
    if settings.vector_backend != "pgvector":
        # InMemoryVectorStore is process-local - running this script as a
        # standalone process would populate a store that vanishes the
        # moment the script exits, with zero effect on the real running
        # API process. app.main's own startup warm-up already re-runs
        # warm_vector_index_from_db with whatever embedder get_embedder()
        # currently resolves to, so simply restarting the API after
        # changing MOCK_LLM/GOOGLE_API_KEY/EMBEDDING_MODEL achieves the
        # same cutover for this backend - nothing for this script to do.
        print(
            f"VECTOR_BACKEND={settings.vector_backend!r} - the in-memory vector store is "
            "process-local, so this script has nothing durable to re-embed. Restart the API "
            "process instead; its own startup warm-up will re-embed every chunk using "
            "whichever embedder is currently configured."
        )
        return

    await init_models()

    embedder = get_embedder()
    print(f"Re-embedding every knowledge chunk using {embedder.model!r} ({embedder.embedding_version!r}).")

    session_factory = get_sessionmaker()
    async with session_factory() as session:
        vector_store = get_vector_store(session)
        count = await warm_vector_index_from_db(session, embedder=embedder, vector_store=vector_store)
        await session.commit()

    print(f"Done: {count} chunk(s) re-embedded.")


def main() -> None:
    asyncio.run(reembed_all())


if __name__ == "__main__":
    main()
