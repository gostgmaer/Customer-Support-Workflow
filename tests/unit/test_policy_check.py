"""app.agents.policy_check's commerce-eligibility gate (spec: Phase 12).

A duck-typed fake Retriever/LLM stand in for the real Retriever/LLMProvider
(neither is a Protocol requiring subclassing) - mirrors the stub-LLM
pattern already established in test_resolution_storefront.py/
test_external_tools.py.
"""

from __future__ import annotations

import pytest

from app.agents.policy_check import CommerceEligibilityCheck, check_commerce_policy, check_policy_eligibility
from app.llm.base import LLMMessage, UsageCallback
from app.rag.retriever import RetrievedDocument

pytestmark = pytest.mark.asyncio

_REFUND_POLICY_DOC = RetrievedDocument(
    document_id="doc_1",
    chunk_id="chunk_1",
    title="Refund Policy",
    source="refund_policy.md",
    category="refunds",
    text=(
        "Customers may request a full refund within 30 days of delivery for items "
        "that arrive damaged, defective, or significantly not as described."
    ),
    score=0.9,
)


class _StubRetriever:
    def __init__(self, docs: list[RetrievedDocument]) -> None:
        self._docs = docs
        self.calls: list[tuple[str, str, int]] = []

    async def retrieve(self, query: str, *, tenant_id: str, top_k: int = 4, **_):
        self.calls.append((query, tenant_id, top_k))
        return self._docs


class _StubLLM:
    def __init__(self, qualifies: str, reason: str = "stub reason") -> None:
        self._qualifies = qualifies
        self._reason = reason
        self.calls = 0

    async def generate(
        self, messages: list[LLMMessage], *, max_tokens: int = 1024, usage_callback=None
    ) -> str:
        raise NotImplementedError

    async def generate_structured(
        self,
        messages: list[LLMMessage],
        *,
        schema,
        max_tokens: int = 1024,
        usage_callback: UsageCallback | None = None,
    ):
        assert schema is CommerceEligibilityCheck
        self.calls += 1
        return CommerceEligibilityCheck(qualifies=self._qualifies, reason=self._reason)


class _ExplodingLLM:
    """Any LLM call here means the caller skipped the "insufficient data,
    don't bother the model" fast path - used to assert that path is real,
    not just that its outcome happens to look right."""

    async def generate(self, *a, **k):
        raise AssertionError("should not be called")

    async def generate_structured(self, *a, **k):
        raise AssertionError("generate_structured should not be called when inputs are insufficient")


async def test_unknown_intent_skips_retrieval_and_llm_entirely():
    retriever = _StubRetriever([_REFUND_POLICY_DOC])
    llm = _ExplodingLLM()
    result = await check_commerce_policy(
        retriever, llm, tenant_id="default", intent="PASSWORD_RESET",
        order_status="delivered", order_reference_date="2020-01-01",
    )
    assert result.decision == "insufficient_data"
    assert retriever.calls == []


async def test_no_policy_document_found_degrades_to_insufficient_data():
    retriever = _StubRetriever([])
    llm = _ExplodingLLM()
    result = await check_commerce_policy(
        retriever, llm, tenant_id="default", intent="REFUND",
        order_status="delivered", order_reference_date="2020-01-01",
    )
    assert result.decision == "insufficient_data"


async def test_no_order_status_and_no_reference_date_skips_the_llm_call():
    retriever = _StubRetriever([_REFUND_POLICY_DOC])
    llm = _ExplodingLLM()
    result = await check_commerce_policy(
        retriever, llm, tenant_id="default", intent="REFUND",
        order_status=None, order_reference_date=None,
    )
    assert result.decision == "insufficient_data"
    assert result.policy_title == "Refund Policy"


async def test_policy_denies_the_request():
    retriever = _StubRetriever([_REFUND_POLICY_DOC])
    llm = _StubLLM(qualifies="no", reason="Delivered 90 days ago, past the 30-day window")
    result = await check_commerce_policy(
        retriever, llm, tenant_id="default", intent="REFUND",
        order_status="delivered", order_reference_date="2020-01-01",
    )
    assert result.decision == "deny"
    assert "30-day" in (result.reason or "")
    assert result.policy_title == "Refund Policy"
    assert llm.calls == 1


async def test_policy_allows_the_request():
    retriever = _StubRetriever([_REFUND_POLICY_DOC])
    llm = _StubLLM(qualifies="yes", reason="Delivered 3 days ago, within the window")
    result = await check_commerce_policy(
        retriever, llm, tenant_id="default", intent="RETURNS",
        order_status="delivered", order_reference_date="2020-01-01",
    )
    assert result.decision == "allow"


async def test_llm_returning_insufficient_data_passes_through():
    retriever = _StubRetriever([_REFUND_POLICY_DOC])
    llm = _StubLLM(qualifies="insufficient_data", reason="order status unclear")
    result = await check_commerce_policy(
        retriever, llm, tenant_id="default", intent="REFUND",
        order_status="unknown", order_reference_date=None,
    )
    assert result.decision == "insufficient_data"


async def test_retrieval_failure_degrades_gracefully_instead_of_raising():
    class _BrokenRetriever:
        async def retrieve(self, *a, **k):
            raise RuntimeError("vector store unreachable")

    llm = _ExplodingLLM()
    result = await check_commerce_policy(
        _BrokenRetriever(), llm, tenant_id="default", intent="REFUND",
        order_status="delivered", order_reference_date="2020-01-01",
    )
    assert result.decision == "insufficient_data"


async def test_llm_failure_degrades_gracefully_instead_of_raising():
    class _BrokenLLM:
        async def generate(self, *a, **k):
            raise NotImplementedError

        async def generate_structured(self, *a, **k):
            raise RuntimeError("provider timeout")

    retriever = _StubRetriever([_REFUND_POLICY_DOC])
    result = await check_commerce_policy(
        retriever, _BrokenLLM(), tenant_id="default", intent="REFUND",
        order_status="delivered", order_reference_date="2020-01-01",
    )
    assert result.decision == "insufficient_data"
    assert result.policy_title == "Refund Policy"


async def test_exchange_intent_reuses_the_return_policy_query():
    """spec: Phase 13 - EXCHANGE was added to _POLICY_QUERIES, reusing the
    same query as RETURNS (no dedicated seeded Exchange Policy doc)."""
    retriever = _StubRetriever([_REFUND_POLICY_DOC])
    llm = _StubLLM(qualifies="yes", reason="within the window")
    result = await check_commerce_policy(
        retriever, llm, tenant_id="default", intent="EXCHANGE",
        order_status="delivered", order_reference_date="2020-01-01",
    )
    assert result.decision == "allow"
    assert "exchange" in retriever.calls[0][0].lower()


# --- check_policy_eligibility: the generic form (spec: Phase 13) ---

_SUBSCRIPTION_POLICY_DOC = RetrievedDocument(
    document_id="doc_2",
    chunk_id="chunk_2",
    title="Subscription Policy",
    source="subscription_policy.md",
    category="subscription",
    text=(
        "Customers on an annual plan who cancel within 14 days of the original purchase "
        "are eligible for a prorated refund - route these to the refund process instead "
        "of a plain cancellation."
    ),
    score=0.9,
)


async def test_check_policy_eligibility_denies_with_a_custom_question_and_facts():
    retriever = _StubRetriever([_SUBSCRIPTION_POLICY_DOC])
    llm = _StubLLM(qualifies="no", reason="Not an annual plan")
    result = await check_policy_eligibility(
        retriever, llm, tenant_id="default",
        query="subscription cancellation refund window",
        question="Should this cancellation route to a refund instead of a plain cancel?",
        facts={"plan": "Pro Monthly", "days since purchase": "5"},
    )
    assert result.decision == "deny"
    assert result.policy_title == "Subscription Policy"


async def test_check_policy_eligibility_allows_with_a_custom_question_and_facts():
    retriever = _StubRetriever([_SUBSCRIPTION_POLICY_DOC])
    llm = _StubLLM(qualifies="yes", reason="Annual plan, within 14 days")
    result = await check_policy_eligibility(
        retriever, llm, tenant_id="default",
        query="subscription cancellation refund window",
        question="Should this cancellation route to a refund instead of a plain cancel?",
        facts={"plan": "Pro Annual", "days since purchase": "3"},
    )
    assert result.decision == "allow"


async def test_check_policy_eligibility_no_facts_skips_the_llm_call():
    retriever = _StubRetriever([_SUBSCRIPTION_POLICY_DOC])
    llm = _ExplodingLLM()
    result = await check_policy_eligibility(
        retriever, llm, tenant_id="default",
        query="subscription cancellation refund window",
        question="Should this cancellation route to a refund instead of a plain cancel?",
        facts={"plan": None, "days since purchase": None},
    )
    assert result.decision == "insufficient_data"
    assert result.policy_title == "Subscription Policy"


async def test_check_policy_eligibility_no_document_found_degrades():
    retriever = _StubRetriever([])
    llm = _ExplodingLLM()
    result = await check_policy_eligibility(
        retriever, llm, tenant_id="default",
        query="a query with no matching document",
        question="does anything match?",
        facts={"x": "y"},
    )
    assert result.decision == "insufficient_data"
