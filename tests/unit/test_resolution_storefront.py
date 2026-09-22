"""app.agents.resolution's storefront-primary commerce routing (spec:
Phase 7 A2). Covers `_get_storefront_integration`, `resolve_via_storefront`,
and `gather_resolution_facts`'s dispatch decision between the internal
DB-backed resolvers and a connected storefront. Uses a stub LLM (not
MockLLMProvider, which always declines the ExternalToolSelection schema -
see app.llm.providers.mock's docstring) and respx for the OpenAPI HTTP
calls, matching the established pattern in test_external_tools.py /
test_human_approval_external.py.
"""

from __future__ import annotations

import respx
from httpx import Response

from app.agents.resolution import (
    _get_storefront_integration,
    gather_resolution_facts,
    resolve_via_storefront,
)
from app.agents.schemas import ExternalToolSelection
from app.db.base import DEFAULT_TENANT_ID
from app.domain.models import Integration
from app.integrations.base import encode_credentials
from app.llm.base import LLMMessage, UsageCallback
from app.repositories.integrations import IntegrationRepository
from app.tools.base import ToolContext

_CANCEL_SPEC = [
    {
        "operation_id": "cancelOrder",
        "method": "POST",
        "path": "/orders/{orderId}/cancel",
        "summary": "Cancel an order",
        "input_schema": {
            "type": "object",
            "properties": {"orderId": {"type": "string"}},
            "required": ["orderId"],
        },
        "param_locations": {"orderId": "path"},
    }
]

_STATUS_SPEC = [
    {
        "operation_id": "getOrder",
        "method": "GET",
        "path": "/orders/{orderId}",
        "summary": "Fetch order status",
        "input_schema": {
            "type": "object",
            "properties": {"orderId": {"type": "string"}},
            "required": ["orderId"],
        },
        "param_locations": {"orderId": "path"},
    }
]


class _StubLLM:
    def __init__(self, selection: ExternalToolSelection) -> None:
        self._selection = selection

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
        assert schema is ExternalToolSelection
        return self._selection


async def _ctx(db_session, *, workflow_run_id: str = "wf_1") -> ToolContext:
    return ToolContext(
        session=db_session,
        requesting_customer_id="cust_1",
        workflow_run_id=workflow_run_id,
        tenant_id=DEFAULT_TENANT_ID,
    )


async def _add_storefront(
    db_session, *, spec_cache: list[dict], auto_execute_reads: bool = False
) -> Integration:
    integration = Integration(
        id="int_storefront_1",
        tenant_id=DEFAULT_TENANT_ID,
        name="Storefront API",
        type="openapi",
        base_url="https://storefront.example.com",
        auth_type="bearer",
        encrypted_credentials=encode_credentials({"token": "t"}),
        config={
            "spec_url": "https://storefront.example.com/openapi.json",
            "spec_cache": spec_cache,
            "role": "storefront",
            "auto_execute_reads": auto_execute_reads,
        },
        enabled=True,
        created_by="staff_1",
    )
    return await IntegrationRepository(db_session, DEFAULT_TENANT_ID).create(integration)


async def test_get_storefront_integration_returns_none_when_unconfigured(db_session):
    ctx = await _ctx(db_session)

    assert await _get_storefront_integration(ctx) is None


async def test_get_storefront_integration_ignores_integration_without_storefront_role(db_session):
    integration = Integration(
        id="int_plain_openapi",
        tenant_id=DEFAULT_TENANT_ID,
        name="Some Other API",
        type="openapi",
        base_url="https://other.example.com",
        auth_type="bearer",
        encrypted_credentials=encode_credentials({"token": "t"}),
        config={"spec_url": "https://other.example.com/openapi.json", "spec_cache": _STATUS_SPEC},
        enabled=True,
        created_by="staff_1",
    )
    await IntegrationRepository(db_session, DEFAULT_TENANT_ID).create(integration)
    ctx = await _ctx(db_session)

    assert await _get_storefront_integration(ctx) is None


async def test_get_storefront_integration_finds_tagged_integration(db_session):
    await _add_storefront(db_session, spec_cache=_STATUS_SPEC)
    ctx = await _ctx(db_session)

    found = await _get_storefront_integration(ctx)

    assert found is not None
    assert found.name == "Storefront API"


async def test_resolve_via_storefront_no_matching_operation_sets_escalation_reason(db_session):
    storefront = await _add_storefront(db_session, spec_cache=_STATUS_SPEC)
    ctx = await _ctx(db_session)
    stub_llm = _StubLLM(ExternalToolSelection(tool_index=-1))

    outcome = await resolve_via_storefront(ctx, stub_llm, "where is my order", storefront, "conv_1")

    assert outcome.escalation_reason is not None
    assert outcome.awaiting_approval is False


async def test_resolve_via_storefront_mutating_action_always_requires_approval(db_session):
    # cancelOrder is a POST - even with auto_execute_reads on, a mutating
    # action must still go through the staff-approval gate.
    storefront = await _add_storefront(db_session, spec_cache=_CANCEL_SPEC, auto_execute_reads=True)
    ctx = await _ctx(db_session)
    selection = ExternalToolSelection(tool_index=0, arguments={"orderId": "order_1001"})

    outcome = await resolve_via_storefront(ctx, _StubLLM(selection), "cancel my order", storefront, "conv_1")

    assert outcome.awaiting_approval is True
    assert outcome.pending_mcp_call is not None
    assert outcome.pending_mcp_call["source"] == "openapi"
    assert outcome.pending_mcp_call["tool_name"] == "cancelOrder"


async def test_resolve_via_storefront_read_requires_approval_without_opt_in(db_session):
    # getOrder is a GET but auto_execute_reads defaults False - must still
    # require approval.
    storefront = await _add_storefront(db_session, spec_cache=_STATUS_SPEC, auto_execute_reads=False)
    ctx = await _ctx(db_session)
    selection = ExternalToolSelection(tool_index=0, arguments={"orderId": "order_1001"})

    outcome = await resolve_via_storefront(
        ctx, _StubLLM(selection), "where is my order", storefront, "conv_1"
    )

    assert outcome.awaiting_approval is True
    assert outcome.pending_mcp_call is not None


@respx.mock
async def test_resolve_via_storefront_auto_executes_read_when_opted_in(db_session, seeded_workflow_run):
    storefront = await _add_storefront(db_session, spec_cache=_STATUS_SPEC, auto_execute_reads=True)
    respx.get("https://storefront.example.com/orders/order_1001").mock(
        return_value=Response(200, json={"status": "shipped", "orderId": "order_1001"})
    )
    ctx = await _ctx(db_session, workflow_run_id=seeded_workflow_run["workflow_run_id"])
    selection = ExternalToolSelection(tool_index=0, arguments={"orderId": "order_1001"})

    outcome = await resolve_via_storefront(
        ctx, _StubLLM(selection), "where is my order", storefront, seeded_workflow_run["conversation_id"]
    )

    assert outcome.awaiting_approval is False
    assert outcome.pending_mcp_call is None
    assert any("shipped" in fact for fact in outcome.facts)


@respx.mock
async def test_resolve_via_storefront_auto_execute_failure_escalates_without_ticket(
    db_session, seeded_workflow_run
):
    storefront = await _add_storefront(db_session, spec_cache=_STATUS_SPEC, auto_execute_reads=True)
    respx.get("https://storefront.example.com/orders/order_1001").mock(return_value=Response(500))
    ctx = await _ctx(db_session, workflow_run_id=seeded_workflow_run["workflow_run_id"])
    selection = ExternalToolSelection(tool_index=0, arguments={"orderId": "order_1001"})

    outcome = await resolve_via_storefront(
        ctx, _StubLLM(selection), "where is my order", storefront, seeded_workflow_run["conversation_id"]
    )

    assert outcome.awaiting_approval is False
    assert outcome.escalation_reason is not None


@respx.mock
async def test_gather_resolution_facts_routes_commerce_intent_to_storefront_when_connected(
    db_session, seeded_workflow_run
):
    await _add_storefront(db_session, spec_cache=_STATUS_SPEC, auto_execute_reads=True)
    respx.get("https://storefront.example.com/orders/order_1001").mock(
        return_value=Response(200, json={"status": "shipped", "orderId": "order_1001"})
    )
    ctx = await _ctx(db_session, workflow_run_id=seeded_workflow_run["workflow_run_id"])
    selection = ExternalToolSelection(tool_index=0, arguments={"orderId": "order_1001"})

    outcome = await gather_resolution_facts(
        ctx,
        intent="ORDER_STATUS",
        customer_id="cust_1",
        conversation_id=seeded_workflow_run["conversation_id"],
        message_id="m1",
        message="where is my order",
        history=[],
        retrieved_documents=[],
        llm=_StubLLM(selection),
    )

    # Proves the internal get_order_history resolver was bypassed - it
    # would have produced a "no orders found"/tool_calls entry naming
    # get_order_history, not a fact naming the storefront's own response.
    assert any("shipped" in fact for fact in outcome.facts)
    assert not any(call.get("tool") == "get_order_history" for call in outcome.tool_calls)


_REFUND_SPEC = [
    {
        "operation_id": "refundOrder",
        "method": "POST",
        "path": "/orders/{orderId}/refund",
        "summary": "Refund an order",
        "input_schema": {
            "type": "object",
            "properties": {"orderId": {"type": "string"}},
            "required": ["orderId"],
        },
        "param_locations": {"orderId": "path"},
    },
    {
        "operation_id": "getOrder",
        "method": "GET",
        "path": "/orders/{orderId}",
        "summary": "Fetch order status",
        "input_schema": {
            "type": "object",
            "properties": {"orderId": {"type": "string"}},
            "required": ["orderId"],
        },
        "param_locations": {"orderId": "path"},
    },
]


class _SequencedStubLLM:
    """Returns canned structured responses in the order enqueued, keyed by
    schema type - needed because resolve_via_storefront's policy-check
    path (spec: Phase 12) makes up to three distinct generate_structured
    calls in sequence: the original proposal, a second read-only lookup
    for order status/date, then the policy eligibility check itself."""

    def __init__(self, responses: dict) -> None:
        self._responses = {k: list(v) for k, v in responses.items()}
        self.calls: list = []

    async def generate(self, *a, **k):
        raise NotImplementedError

    async def generate_structured(self, messages, *, schema, max_tokens=1024, usage_callback=None):
        self.calls.append(schema)
        queue = self._responses.get(schema)
        assert queue, f"no stubbed response left for {schema}"
        return queue.pop(0)


def _refund_policy_doc():
    from app.rag.retriever import RetrievedDocument

    return RetrievedDocument(
        document_id="doc_1", chunk_id="c1", title="Refund Policy", source="refund_policy.md",
        category="refunds", text="Full refund within 30 days of delivery.", score=0.9,
    )


class _StubPolicyRetriever:
    async def retrieve(self, query, *, tenant_id, top_k=4, **_):
        return [_refund_policy_doc()]


@respx.mock
async def test_resolve_via_storefront_refund_policy_gate_denies_before_calling_refund(db_session):
    from app.agents.policy_check import CommerceEligibilityCheck

    await _add_storefront(db_session, spec_cache=_REFUND_SPEC)
    lookup_route = respx.get("https://storefront.example.com/orders/order_1001").mock(
        return_value=Response(200, json={"status": "delivered", "deliveredAt": "2020-01-01"})
    )
    refund_route = respx.post("https://storefront.example.com/orders/order_1001/refund").mock(
        return_value=Response(200, json={"status": "refund_issued"})
    )
    ctx = await _ctx(db_session)
    llm = _SequencedStubLLM(
        {
            ExternalToolSelection: [
                ExternalToolSelection(tool_index=0, arguments={"orderId": "order_1001"}),  # refund proposal
                ExternalToolSelection(tool_index=1, arguments={"orderId": "order_1001"}),  # status lookup
            ],
            CommerceEligibilityCheck: [
                CommerceEligibilityCheck(qualifies="no", reason="Delivered 2020-01-01, past 30-day window"),
            ],
        }
    )

    outcome = await gather_resolution_facts(
        ctx,
        intent="REFUND",
        customer_id="cust_1",
        conversation_id="conv_1",
        message_id="m1",
        message="I'd like a refund for order 1001",
        history=[],
        retrieved_documents=[],
        llm=llm,
        retriever=_StubPolicyRetriever(),
    )

    assert outcome.awaiting_approval is False
    assert outcome.pending_mcp_call is None
    assert any("30-day" in fact for fact in outcome.facts)
    assert lookup_route.called
    assert not refund_route.called


@respx.mock
async def test_resolve_via_storefront_refund_policy_gate_allows_and_proceeds_to_approval(db_session):
    from app.agents.policy_check import CommerceEligibilityCheck

    storefront = await _add_storefront(db_session, spec_cache=_REFUND_SPEC)
    respx.get("https://storefront.example.com/orders/order_1001").mock(
        return_value=Response(200, json={"status": "delivered", "deliveredAt": "2026-09-20"})
    )
    ctx = await _ctx(db_session)
    llm = _SequencedStubLLM(
        {
            ExternalToolSelection: [
                ExternalToolSelection(tool_index=0, arguments={"orderId": "order_1001"}),
                ExternalToolSelection(tool_index=1, arguments={"orderId": "order_1001"}),
            ],
            CommerceEligibilityCheck: [
                CommerceEligibilityCheck(qualifies="yes", reason="Within the 30-day window"),
            ],
        }
    )

    outcome = await resolve_via_storefront(
        ctx, llm, "I'd like a refund for order 1001", storefront, "conv_1", intent="REFUND",
        retriever=_StubPolicyRetriever(),
    )

    assert outcome.awaiting_approval is True
    assert outcome.pending_mcp_call is not None
    assert outcome.pending_mcp_call["tool_name"] == "refundOrder"


async def test_resolve_via_storefront_order_cancel_skips_the_policy_gate_entirely(db_session):
    """ORDER_CANCEL deliberately gets no policy-check call at all (the
    storefront's own mutating operation already enforces its status rule
    deterministically) - proven by an LLM that would fail the test if
    asked for a CommerceEligibilityCheck it was never stubbed to answer."""
    storefront = await _add_storefront(db_session, spec_cache=_CANCEL_SPEC)
    ctx = await _ctx(db_session)
    llm = _SequencedStubLLM(
        {ExternalToolSelection: [ExternalToolSelection(tool_index=0, arguments={"orderId": "order_1001"})]}
    )

    outcome = await resolve_via_storefront(
        ctx, llm, "cancel my order 1001", storefront, "conv_1", intent="ORDER_CANCEL",
        retriever=_StubPolicyRetriever(),
    )

    assert outcome.awaiting_approval is True


async def test_gather_resolution_facts_falls_back_to_internal_resolver_without_storefront(
    db_session, seeded_customer, seeded_workflow_run
):
    customer_id = seeded_customer["customer_id"]
    ctx = ToolContext(
        session=db_session,
        requesting_customer_id=customer_id,
        workflow_run_id=seeded_workflow_run["workflow_run_id"],
        tenant_id=DEFAULT_TENANT_ID,
    )

    outcome = await gather_resolution_facts(
        ctx,
        intent="ORDER_STATUS",
        customer_id=customer_id,
        conversation_id=seeded_workflow_run["conversation_id"],
        message_id="m1",
        message="where is my order",
        history=[],
        retrieved_documents=[],
        llm=None,
    )

    # No storefront connected - the existing internal DB resolver path
    # (get_order_history) must run exactly as before this phase.
    assert any(call.get("tool") == "get_order_history" for call in outcome.tool_calls)


# --- Phase 8.3: new commerce intents get storefront routing "for free" ---


async def test_exchange_has_no_internal_resolver_but_routes_via_storefront(db_session):
    """EXCHANGE deliberately has no INTENT_RESOLVERS entry (see that
    dict's comment in app.agents.resolution) - a connected storefront
    must still handle it via the exact same COMMERCE_INTENTS membership
    every other commerce intent uses, proving the "for free" routing
    claim rather than just asserting set membership."""
    exchange_spec = [
        {
            "operation_id": "exchangeOrder",
            "method": "POST",
            "path": "/orders/{orderId}/exchange",
            "summary": "Exchange an order for a different variant",
            "input_schema": {
                "type": "object",
                "properties": {"orderId": {"type": "string"}, "requestedVariant": {"type": "string"}},
                "required": ["orderId", "requestedVariant"],
            },
            "param_locations": {"orderId": "path", "requestedVariant": "body_field"},
        }
    ]
    await _add_storefront(db_session, spec_cache=exchange_spec)
    ctx = await _ctx(db_session)
    selection = ExternalToolSelection(
        tool_index=0, arguments={"orderId": "order_1001", "requestedVariant": "size-M"}
    )

    outcome = await gather_resolution_facts(
        ctx,
        intent="EXCHANGE",
        customer_id="cust_1",
        conversation_id="conv_1",
        message_id="m1",
        message="I'd like to exchange my order for a size M.",
        history=[],
        retrieved_documents=[],
        llm=_StubLLM(selection),
    )

    assert outcome.awaiting_approval is True
    assert outcome.pending_mcp_call is not None
    assert outcome.pending_mcp_call["tool_name"] == "exchangeOrder"


async def test_exchange_without_storefront_escalates_via_knowledge_fallback(db_session, seeded_workflow_run):
    """No INTENT_RESOLVERS entry AND no storefront - must fall through to
    resolve_from_knowledge's real escalation, not a silent no-op
    ResolutionOutcome()."""
    ctx = ToolContext(
        session=db_session,
        requesting_customer_id="cust_1",
        workflow_run_id=seeded_workflow_run["workflow_run_id"],
        tenant_id=DEFAULT_TENANT_ID,
    )

    outcome = await gather_resolution_facts(
        ctx,
        intent="EXCHANGE",
        customer_id="cust_1",
        conversation_id=seeded_workflow_run["conversation_id"],
        message_id="m1",
        message="I'd like to exchange my order for a size M.",
        history=[],
        retrieved_documents=[],
        llm=None,
    )

    assert outcome.escalation_reason is not None


# --- Phase 8.4: best-effort webhook correlation ---


async def test_resolve_via_storefront_records_order_id_for_webhook_correlation(
    db_session, seeded_workflow_run
):
    from app.domain.models import Conversation

    storefront = await _add_storefront(db_session, spec_cache=_CANCEL_SPEC)
    ctx = ToolContext(
        session=db_session,
        requesting_customer_id="cust_1",
        workflow_run_id=seeded_workflow_run["workflow_run_id"],
        tenant_id=DEFAULT_TENANT_ID,
    )
    selection = ExternalToolSelection(tool_index=0, arguments={"orderId": "order_1001"})

    await resolve_via_storefront(
        ctx, _StubLLM(selection), "cancel my order", storefront, seeded_workflow_run["conversation_id"]
    )

    conversation = await db_session.get(Conversation, seeded_workflow_run["conversation_id"])
    assert conversation.metadata_json.get("last_order_id") == "order_1001"


async def test_resolve_via_storefront_no_order_argument_records_nothing(db_session, seeded_workflow_run):
    from app.domain.models import Conversation

    # _STATUS_SPEC's getOrder operation takes "orderId" - use a proposal
    # whose only argument doesn't mention "order" at all, to prove this
    # is a no-op (not an error) when there's nothing to correlate on.
    no_order_spec = [
        {
            "operation_id": "getSubscription",
            "method": "GET",
            "path": "/subscriptions/{customerRef}",
            "summary": "Get a subscription",
            "input_schema": {
                "type": "object",
                "properties": {"customerRef": {"type": "string"}},
                "required": ["customerRef"],
            },
            "param_locations": {"customerRef": "path"},
        }
    ]
    storefront = await _add_storefront(db_session, spec_cache=no_order_spec)
    ctx = ToolContext(
        session=db_session,
        requesting_customer_id="cust_1",
        workflow_run_id=seeded_workflow_run["workflow_run_id"],
        tenant_id=DEFAULT_TENANT_ID,
    )
    selection = ExternalToolSelection(tool_index=0, arguments={"customerRef": "CUST-1"})

    await resolve_via_storefront(
        ctx, _StubLLM(selection), "what's my plan", storefront, seeded_workflow_run["conversation_id"]
    )

    conversation = await db_session.get(Conversation, seeded_workflow_run["conversation_id"])
    assert "last_order_id" not in conversation.metadata_json
