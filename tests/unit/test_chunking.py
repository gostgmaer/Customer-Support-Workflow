from datetime import UTC, datetime

from app.rag.chunking import CHUNKING_VERSION, build_chunks, chunk_text
from app.rag.loaders import LoadedDocument


def _doc(text: str, **overrides) -> LoadedDocument:
    defaults = dict(
        title="Test Doc",
        source="test:doc",
        category="general",
        version="1.0",
        effective_date=datetime(2026, 1, 1, tzinfo=UTC),
        expiration_date=None,
        language="en",
        text=text,
    )
    defaults.update(overrides)
    return LoadedDocument(**defaults)


def test_chunk_text_splits_on_markdown_headings():
    text = "# Refund Policy\n\nRefunds within 30 days.\n\n## Eligibility\n\nOnly unused items qualify."
    chunks = chunk_text(text, max_chars=800, overlap=100)
    assert len(chunks) == 2
    assert chunks[0][1] == ["Refund Policy"]
    assert chunks[1][1] == ["Refund Policy", "Eligibility"]
    assert "Refund Policy" in chunks[0][0]  # heading kept inline, not stripped
    assert "Eligibility" in chunks[1][0]


def test_chunk_text_keeps_a_gfm_table_intact_within_its_section():
    text = (
        "# Shipping Windows\n\n"
        "See the table below.\n\n"
        "| Region | Days |\n"
        "| --- | --- |\n"
        "| US | 3 |\n"
        "| EU | 7 |\n"
    )
    chunks = chunk_text(text, max_chars=800, overlap=100)
    assert len(chunks) == 1
    assert "| Region | Days |" in chunks[0][0]
    assert "| US | 3 |" in chunks[0][0]
    assert "| EU | 7 |" in chunks[0][0]


def test_chunk_text_with_no_headings_returns_one_section_with_empty_path():
    chunks = chunk_text("Just a plain paragraph with no markdown headings at all.")
    assert len(chunks) == 1
    assert chunks[0][1] == []


def test_chunk_text_of_empty_string_is_empty():
    assert chunk_text("") == []


def test_chunk_text_sub_splits_a_section_over_max_chars():
    long_section = "# Long Section\n\n" + ("word " * 400)
    chunks = chunk_text(long_section, max_chars=200, overlap=20)
    assert len(chunks) > 1
    for text, section_path in chunks:
        assert len(text) <= 220  # a little slack for the splitter's own boundary rules
        assert section_path == ["Long Section"]


def test_build_chunks_stamps_rich_metadata():
    doc = _doc("# Policy\n\nSome policy text here.")
    chunks = build_chunks(doc, document_id="doc-1")
    assert len(chunks) == 1
    meta = chunks[0].metadata
    assert meta["document_id"] == "doc-1"
    assert meta["title"] == "Test Doc"
    assert meta["chunking_version"] == CHUNKING_VERSION
    assert meta["section_path"] == ["Policy"]
    assert len(meta["content_hash"]) == 32
    assert meta["token_count"] >= 1


def test_build_chunks_gives_each_chunk_its_own_metadata_dict():
    # Regression: the old implementation built ONE metadata dict and
    # reused the same object reference for every chunk - harmless only
    # because nothing mutated it in place. Per-chunk fields (content_hash,
    # section_path) make that no longer true, so distinct dict identity
    # per chunk is now a real correctness requirement, not just hygiene.
    doc = _doc("# One\n\nFirst.\n\n# Two\n\nSecond.")
    chunks = build_chunks(doc, document_id="doc-1")
    assert len(chunks) == 2
    assert chunks[0].metadata is not chunks[1].metadata
    assert chunks[0].metadata["content_hash"] != chunks[1].metadata["content_hash"]


def test_build_chunks_content_hash_is_stable_for_identical_text():
    doc_a = _doc("# Policy\n\nSame text.")
    doc_b = _doc("# Policy\n\nSame text.", title="Different Title")
    hash_a = build_chunks(doc_a, document_id="doc-a")[0].metadata["content_hash"]
    hash_b = build_chunks(doc_b, document_id="doc-b")[0].metadata["content_hash"]
    assert hash_a == hash_b  # hash is over chunk text only, not surrounding metadata
