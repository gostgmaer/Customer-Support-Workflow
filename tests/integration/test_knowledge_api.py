"""Staff-facing Knowledge Base browse/search API (spec: help-desk-kit-style
KB) - GET /api/v1/knowledge/categories, /articles, /articles/{id},
/articles/{id}/related, POST .../feedback, and POST /upload.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
from docx import Document
from pypdf import PdfWriter
from reportlab.pdfgen import canvas

from app.db.base import DEFAULT_TENANT_ID
from app.domain.models import KnowledgeDocument
from app.rag.retriever import Retriever
from app.repositories.vector_store import InMemoryVectorStore


async def _make_article(
    db_session,
    *,
    title: str,
    category: str,
    raw_text: str = "Some article body text.",
    tenant_id: str = DEFAULT_TENANT_ID,
) -> KnowledgeDocument:
    doc = KnowledgeDocument(
        title=title,
        source="test-fixture",
        category=category,
        version="1.0",
        effective_date=datetime.now(UTC),
        language="en",
        raw_text=raw_text,
        tenant_id=tenant_id,
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    return doc


@pytest.mark.asyncio
async def test_list_categories_groups_by_category(client, staff_token, db_session):
    await _make_article(db_session, title="Refund basics", category="Billing")
    await _make_article(db_session, title="Refund edge cases", category="Billing")
    await _make_article(db_session, title="SSO setup", category="Security")

    response = await client.get(
        "/api/v1/knowledge/categories", headers={"Authorization": f"Bearer {staff_token}"}
    )
    assert response.status_code == 200
    by_category = {row["category"]: row["article_count"] for row in response.json()}
    assert by_category == {"Billing": 2, "Security": 1}


@pytest.mark.asyncio
async def test_list_articles_filters_by_category_and_search(client, staff_token, db_session):
    await _make_article(db_session, title="Refund basics", category="Billing", raw_text="How refunds work.")
    await _make_article(db_session, title="SSO setup", category="Security", raw_text="Configure SSO here.")
    headers = {"Authorization": f"Bearer {staff_token}"}

    by_category = await client.get("/api/v1/knowledge/articles?category=Security", headers=headers)
    titles = {a["title"] for a in by_category.json()}
    assert titles == {"SSO setup"}

    by_search = await client.get("/api/v1/knowledge/articles?q=refund", headers=headers)
    titles = {a["title"] for a in by_search.json()}
    assert titles == {"Refund basics"}


@pytest.mark.asyncio
async def test_get_article_increments_view_count_without_bumping_updated_at(client, staff_token, db_session):
    doc = await _make_article(db_session, title="Refund basics", category="Billing")
    headers = {"Authorization": f"Bearer {staff_token}"}

    first = await client.get(f"/api/v1/knowledge/articles/{doc.id}", headers=headers)
    assert first.status_code == 200
    assert first.json()["view_count"] == 1

    second = await client.get(f"/api/v1/knowledge/articles/{doc.id}", headers=headers)
    assert second.json()["view_count"] == 2
    # A mere read must never look like a content edit - "recently updated"
    # sorts by this field and would drift on every view otherwise (a real
    # bug caught and fixed while building this feature).
    assert second.json()["updated_at"] == first.json()["updated_at"]


@pytest.mark.asyncio
async def test_article_feedback_updates_helpful_percent(client, staff_token, db_session):
    doc = await _make_article(db_session, title="Refund basics", category="Billing")
    headers = {"Authorization": f"Bearer {staff_token}"}

    yes = await client.post(
        f"/api/v1/knowledge/articles/{doc.id}/feedback", json={"helpful": True}, headers=headers
    )
    assert yes.status_code == 200
    assert yes.json()["helpful_percent"] == 100

    no = await client.post(
        f"/api/v1/knowledge/articles/{doc.id}/feedback", json={"helpful": False}, headers=headers
    )
    assert no.json()["helpful_yes_count"] == 1
    assert no.json()["helpful_no_count"] == 1
    assert no.json()["helpful_percent"] == 50


@pytest.mark.asyncio
async def test_related_articles_share_category_excluding_self(client, staff_token, db_session):
    a = await _make_article(db_session, title="Refund basics", category="Billing")
    b = await _make_article(db_session, title="Refund edge cases", category="Billing")
    await _make_article(db_session, title="SSO setup", category="Security")
    headers = {"Authorization": f"Bearer {staff_token}"}

    response = await client.get(f"/api/v1/knowledge/articles/{a.id}/related", headers=headers)
    titles = {row["title"] for row in response.json()}
    assert titles == {b.title}


@pytest.mark.asyncio
async def test_unknown_article_returns_validation_error(client, staff_token):
    response = await client.get(
        "/api/v1/knowledge/articles/does-not-exist", headers={"Authorization": f"Bearer {staff_token}"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_knowledge_base_is_tenant_scoped(client, staff_token, db_session):
    await _make_article(db_session, title="Tenant A article", category="Billing", tenant_id=DEFAULT_TENANT_ID)
    await _make_article(db_session, title="Tenant B article", category="Billing", tenant_id="tenant_b")

    response = await client.get(
        "/api/v1/knowledge/articles", headers={"Authorization": f"Bearer {staff_token}"}
    )
    titles = {row["title"] for row in response.json()}
    assert titles == {"Tenant A article"}


@pytest.mark.asyncio
async def test_non_admin_cannot_upload(client, staff_token):
    files = {"file": ("policy.md", b"# Return Policy\n\nReturns within 30 days.", "text/markdown")}
    data = {"title": "Return Policy", "category": "refunds"}
    response = await client.post(
        "/api/v1/knowledge/upload",
        files=files,
        data=data,
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_upload_creates_a_retrievable_article(client, admin_staff_token, db_session):
    content = b"Customers may return an item within 30 days of purchase under our return policy."
    files = {"file": ("return_policy.md", content, "text/markdown")}
    data = {"title": "Return Policy", "category": "returns"}
    headers = {"Authorization": f"Bearer {admin_staff_token}"}

    response = await client.post("/api/v1/knowledge/upload", files=files, data=data, headers=headers)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "Return Policy"
    assert body["category"] == "returns"
    assert body["source"].startswith("upload:")
    assert "return an item within 30 days" in body["raw_text"]

    # Prove it landed in the same RAG index the AI actually queries during
    # chat, not just a row this router happens to be able to read back.
    # The test env's HashingEmbedder is purely lexical (app.rag.embeddings),
    # so the query must share actual words with the content, matching
    # test_docs_sync_route.py's "refund"/"refund policy" precedent.
    retriever = Retriever(InMemoryVectorStore())
    results = await retriever.retrieve("What is your return policy?", tenant_id=DEFAULT_TENANT_ID, top_k=3)
    assert any(r.title == "Return Policy" for r in results)

    # And it shows up through the ordinary browse/list endpoints too.
    listed = await client.get("/api/v1/knowledge/articles?category=returns", headers=headers)
    assert {a["title"] for a in listed.json()} == {"Return Policy"}


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_file_type(client, admin_staff_token):
    files = {"file": ("policy.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")}
    data = {"title": "Return Policy", "category": "returns"}
    response = await client.post(
        "/api/v1/knowledge/upload",
        files=files,
        data=data,
        headers={"Authorization": f"Bearer {admin_staff_token}"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file(client, admin_staff_token):
    oversized = b"x" * (10 * 1024 * 1024 + 1)
    files = {"file": ("policy.txt", oversized, "text/plain")}
    data = {"title": "Too Big", "category": "returns"}
    response = await client.post(
        "/api/v1/knowledge/upload",
        files=files,
        data=data,
        headers={"Authorization": f"Bearer {admin_staff_token}"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_repeated_uploads_of_the_same_filename_both_create_distinct_articles(
    client, admin_staff_token
):
    """Unlike a docs-integration sync (which dedupes/version-bumps on
    (tenant, title, source)), an admin manually uploading the same filename
    twice is a deliberate new document each time - see the upload route's
    own docstring for why."""
    files = {"file": ("policy.md", b"Version one of the policy.", "text/markdown")}
    data = {"title": "Return Policy", "category": "returns"}
    headers = {"Authorization": f"Bearer {admin_staff_token}"}

    first = await client.post("/api/v1/knowledge/upload", files=files, data=data, headers=headers)
    second = await client.post("/api/v1/knowledge/upload", files=files, data=data, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


async def _seed_ingested_article(client, admin_staff_token, *, title: str, category: str, content: bytes):
    """Unlike `_make_article` (a bare DB row), `/ask` retrieves from the
    vector store - seed through the real upload endpoint so a genuine
    chunk+embedding exists to be found."""
    files = {"file": (f"{title.lower().replace(' ', '_')}.md", content, "text/markdown")}
    data = {"title": title, "category": category}
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    response = await client.post("/api/v1/knowledge/upload", files=files, data=data, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_staff_can_ask_and_gets_a_grounded_answer_with_sources(client, admin_staff_token):
    await _seed_ingested_article(
        client,
        admin_staff_token,
        title="Return Policy",
        category="returns",
        content=b"Customers may return an item within 30 days of purchase under our return policy.",
    )
    headers = {"Authorization": f"Bearer {admin_staff_token}"}

    response = await client.post(
        "/api/v1/knowledge/ask", json={"question": "What is your return policy?"}, headers=headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["grounded"] is True
    assert body["answer"]
    assert any(s["title"] == "Return Policy" for s in body["sources"])


@pytest.mark.asyncio
async def test_customer_can_ask_the_same_endpoint(client, admin_staff_token, auth_token):
    await _seed_ingested_article(
        client,
        admin_staff_token,
        title="Shipping Policy",
        category="shipping",
        content=b"Standard shipping takes 5 to 7 business days within the country of purchase.",
    )

    # The test env's HashingEmbedder is purely lexical (app.rag.embeddings) -
    # the query must share actual words with the content, matching this
    # file's other retrieval-proving tests' precedent.
    response = await client.post(
        "/api/v1/knowledge/ask",
        json={"question": "How many business days does standard shipping take?"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["grounded"] is True
    assert any(s["title"] == "Shipping Policy" for s in body["sources"])


@pytest.mark.asyncio
async def test_ask_requires_authentication(client):
    response = await client.post("/api/v1/knowledge/ask", json={"question": "Anything?"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_ask_with_no_matching_content_is_not_grounded(client, staff_token):
    response = await client.post(
        "/api/v1/knowledge/ask",
        json={"question": "What is the airspeed velocity of an unladen swallow?"},
        headers={"Authorization": f"Bearer {staff_token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["grounded"] is False
    assert body["sources"] == []
    assert body["answer"]


@pytest.mark.asyncio
async def test_ask_rejects_blank_question(client, staff_token):
    response = await client.post(
        "/api/v1/knowledge/ask", json={"question": "   "}, headers={"Authorization": f"Bearer {staff_token}"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_upload_extracts_and_ingests_a_real_pdf(client, admin_staff_token):
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "Return Policy")
    c.drawString(72, 700, "Customers may return an item within 30 days of purchase.")
    c.save()

    files = {"file": ("return_policy.pdf", buf.getvalue(), "application/pdf")}
    data = {"title": "Return Policy", "category": "returns"}
    headers = {"Authorization": f"Bearer {admin_staff_token}"}

    response = await client.post("/api/v1/knowledge/upload", files=files, data=data, headers=headers)

    assert response.status_code == 201, response.text
    body = response.json()
    assert "return an item within 30 days" in body["raw_text"]

    ask = await client.post(
        "/api/v1/knowledge/ask",
        json={"question": "How many days do I have to return an item?"},
        headers=headers,
    )
    assert ask.json()["grounded"] is True
    assert any(s["title"] == "Return Policy" for s in ask.json()["sources"])


@pytest.mark.asyncio
async def test_upload_extracts_and_ingests_a_real_docx(client, admin_staff_token):
    document = Document()
    document.add_heading("Shipping Policy", level=1)
    document.add_paragraph("Standard shipping takes 5 to 7 business days to arrive.")
    buf = io.BytesIO()
    document.save(buf)

    files = {
        "file": (
            "shipping_policy.docx",
            buf.getvalue(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    data = {"title": "Shipping Policy", "category": "shipping"}
    headers = {"Authorization": f"Bearer {admin_staff_token}"}

    response = await client.post("/api/v1/knowledge/upload", files=files, data=data, headers=headers)

    assert response.status_code == 201, response.text
    body = response.json()
    assert "# Shipping Policy" in body["raw_text"]
    assert "5 to 7 business days" in body["raw_text"]

    # The full article keeps real markdown (rendered client-side), but the
    # list/card preview must not leak raw "#"/"|" syntax to the reader.
    listed = await client.get("/api/v1/knowledge/articles?category=shipping", headers=headers)
    summary = next(a for a in listed.json() if a["title"] == "Shipping Policy")["summary"]
    assert "#" not in summary
    assert "|" not in summary
    assert "Shipping Policy" in summary
    assert "5 to 7 business days" in summary


@pytest.mark.asyncio
async def test_upload_rejects_encrypted_pdf(client, admin_staff_token):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("secret")
    buf = io.BytesIO()
    writer.write(buf)

    files = {"file": ("policy.pdf", buf.getvalue(), "application/pdf")}
    data = {"title": "Policy", "category": "general"}
    headers = {"Authorization": f"Bearer {admin_staff_token}"}

    response = await client.post("/api/v1/knowledge/upload", files=files, data=data, headers=headers)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert "Encrypted" in response.json()["message"]


@pytest.mark.asyncio
async def test_upload_records_who_uploaded_it_but_seeded_articles_have_no_uploader(
    client, admin_staff_token, seeded_admin, db_session
):
    files = {"file": ("policy.txt", b"Some policy content.", "text/plain")}
    data = {"title": "Some Policy", "category": "general"}
    headers = {"Authorization": f"Bearer {admin_staff_token}"}

    uploaded = await client.post("/api/v1/knowledge/upload", files=files, data=data, headers=headers)
    assert uploaded.json()["created_by"] == seeded_admin["staff_id"]

    # A document that came from make seed/a docs-integration sync has no
    # human uploader to attribute - created_by stays null, not a
    # fabricated "system" placeholder.
    seeded = await _make_article(db_session, title="Seeded Policy", category="general")
    detail = await client.get(f"/api/v1/knowledge/articles/{seeded.id}", headers=headers)
    assert detail.json()["created_by"] is None
