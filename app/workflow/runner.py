"""Compiles the graph with a checkpointer and exposes run/resume entrypoints.

spec: Phase 9.1a - `CHECKPOINT_BACKEND` selects the backend, mirroring
`VECTOR_BACKEND`'s own env-var-selected-backend pattern
(app.repositories.vector_store). `"sqlite"` (default, zero-setup) writes
to a local file (`CHECKPOINT_DB_PATH`), independent of `DATABASE_URL` -
fine for a single instance, but a second API instance can never resume
a run the first one paused, since the file lives on one machine.
`"postgres"` reuses `DATABASE_URL` (translated to a plain `psycopg`-style
DSN - `AsyncPostgresSaver` uses `psycopg`, not SQLAlchemy's `asyncpg`
driver, so the `+asyncpg` suffix must be stripped) so any instance can
resume any paused run - required before scaling human-approval-handling
API instances horizontally (see docs/DEPLOYMENT.md). Verified directly
against the real installed `langgraph-checkpoint-postgres` package
(3.1.2) before writing this - `from_conn_string` is an async context
manager over a plain `postgresql://` DSN, and `.setup()` is a coroutine
that must run once, not on every checkpointer open (see
app.scripts.setup_checkpointer).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.config.dynamic_settings import EffectiveSettings, get_effective_settings
from app.db.base import new_uuid
from app.domain.enums.priority import PRIORITY_ORDER, Priority
from app.domain.exceptions import AuthorizationError
from app.domain.models import SupportTicket, WorkflowRun
from app.integrations.hooks import notify_ticket_created
from app.llm.router import TenantScopedLLMRouter, get_llm_router
from app.observability.logging import bind_context, get_logger
from app.observability.tracing import build_run_metadata, build_run_tags
from app.rag.retriever import Retriever
from app.realtime.connections import get_connection_manager
from app.repositories.conversations import ConversationRepository
from app.repositories.vector_store import get_vector_store
from app.workflow.deps import WorkflowDeps
from app.workflow.graph import build_graph
from app.workflow.state import SupportState

logger = get_logger(__name__)


def _postgres_checkpoint_dsn(database_url: str) -> str:
    """`AsyncPostgresSaver` connects via `psycopg`, which doesn't
    recognize SQLAlchemy's `+asyncpg`/`+psycopg` driver suffix - strip it
    down to the plain `postgresql://` scheme `psycopg.AsyncConnection`
    expects (verified directly against the installed package)."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


@asynccontextmanager
async def get_checkpointer():
    settings = get_settings()
    if settings.checkpoint_backend == "postgres":
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        dsn = _postgres_checkpoint_dsn(settings.database_url)
        async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
            yield saver
    else:
        async with AsyncSqliteSaver.from_conn_string(settings.checkpoint_db_path) as saver:
            yield saver


async def _build_deps(session: AsyncSession, tenant_id: str) -> tuple[WorkflowDeps, EffectiveSettings]:
    effective = await get_effective_settings(session, tenant_id)
    vector_store = get_vector_store(session if get_settings().vector_backend == "pgvector" else None)
    router = TenantScopedLLMRouter(
        get_llm_router(),
        mock_llm=effective.mock_llm,
        default_provider=effective.default_llm_provider,
        fallback_provider=effective.fallback_llm_provider,
    )
    deps = WorkflowDeps(session=session, llm_router=router, retriever=Retriever(vector_store))
    return deps, effective


def _extract_interrupt(result: dict) -> dict | None:
    interrupts = result.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0]
    return getattr(first, "value", first)


async def run_workflow(
    session: AsyncSession,
    *,
    tenant_id: str,
    conversation_id: str,
    customer_id: str,
    message_id: str,
    message: str,
    channel: str,
) -> dict:
    # WorkflowRun.conversation_id is a bare ForeignKey column, not an ORM
    # relationship() - the Conversation row must exist (and be flushed)
    # before WorkflowRun references it, but Conversation creation normally
    # happens later, inside the load_conversation graph node. For a brand
    # new conversation_id (a customer's very first message), that node
    # hadn't run yet, so this would violate the FK on any database that
    # actually enforces it (Postgres always does; SQLite doesn't unless
    # asked - see app.db.session). get_or_create is idempotent, so calling
    # it here and again from load_conversation is a deliberate, cheap
    # safety net, not a bug.
    await ConversationRepository(session, tenant_id).get_or_create(
        conversation_id, customer_id=customer_id, channel=channel
    )
    run = WorkflowRun(
        tenant_id=tenant_id, conversation_id=conversation_id, message_id=message_id, status="running"
    )
    session.add(run)
    await session.flush()
    bind_context(
        request_id=new_uuid(),
        conversation_id=conversation_id,
        customer_id=customer_id,
        workflow_run_id=run.id,
    )

    deps, effective = await _build_deps(session, tenant_id)
    initial_state: SupportState = {
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "customer_id": customer_id,
        "message_id": message_id,
        "latest_message": message,
        "channel": channel,
        "workflow_run_id": run.id,
        "regenerate_count": 0,
        "awaiting_approval": False,
        "runtime_config": {
            "confidence_intent": effective.confidence_intent,
            "confidence_retrieval": effective.confidence_retrieval,
            "escalation_max_failed_attempts": effective.escalation_max_failed_attempts,
        },
    }
    settings = get_settings()
    config: RunnableConfig = {
        "configurable": {"thread_id": run.id, "deps": deps},
        "metadata": build_run_metadata(
            conversation_id=conversation_id,
            customer_id=customer_id,
            channel=channel,
            environment=settings.app_env,
        ),
        "tags": build_run_tags(channel=channel, environment=settings.app_env),
    }

    async with get_checkpointer() as checkpointer:
        graph = build_graph().compile(checkpointer=checkpointer)
        result = await graph.ainvoke(initial_state, config)

    interrupt_payload = _extract_interrupt(result)
    if interrupt_payload is not None:
        logger.info("workflow_awaiting_approval", workflow_run_id=run.id)
        facts = interrupt_payload.get("facts", []) if isinstance(interrupt_payload, dict) else []
        # spec: Phase 8.2 - the interrupt payload IS what human_approval_gate
        # passed to interrupt() (see _extract_interrupt above), which
        # already carries integration_name/tool_name/arguments as top-level
        # keys for an external-tool proposal (type == "mcp_tool_approval")
        # - never for a refund (type == "refund_approval").
        pending_call = None
        if isinstance(interrupt_payload, dict) and interrupt_payload.get("type") == "mcp_tool_approval":
            pending_call = {
                "integration_name": interrupt_payload.get("integration_name"),
                "tool_name": interrupt_payload.get("tool_name"),
                "arguments": interrupt_payload.get("arguments"),
            }
        ticket = SupportTicket(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            customer_id=customer_id,
            workflow_run_id=run.id,
            intent=result.get("intent", "REFUND"),
            priority=result.get("priority", "HIGH"),
            status="open",
            summary="; ".join(facts) or "Refund pending human approval",
            customer_problem=message,
            actions_taken=[c["tool"] for c in result.get("tool_calls", [])],
            tools_used=list({c["tool"] for c in result.get("tool_calls", [])}),
            relevant_documents=[],
            reason_for_escalation="High-risk action requires human approval before proceeding",
            pending_call=pending_call,
        )
        session.add(ticket)
        run.status = "awaiting_approval"
        await session.flush()  # populate ticket.id before notify_ticket_created references it
        await notify_ticket_created(session, tenant_id, ticket)
        conversation = await ConversationRepository(session, tenant_id).get(conversation_id)
        if conversation is not None:
            # save_outcome (spec §30) is what normally sets Conversation.status,
            # but it never runs for this path - the graph is interrupted before
            # reaching it (see build_graph's human_approval_gate). Without this,
            # a customer refreshing mid-approval would see stale "open"/"resolved"
            # from a previous turn instead of the truth.
            conversation.status = "awaiting_approval"
            await session.flush()
        await session.commit()
        return {
            "workflow_run_id": run.id,
            "conversation_id": conversation_id,
            "status": "awaiting_approval",
            "requires_human": True,
            "response": None,
            "ticket_id": ticket.id,
            "interrupt": interrupt_payload,
        }

    requires_human = bool(result.get("requires_human"))
    ticket_id = None
    if requires_human:
        # save_outcome (spec §30) files a ticket for every non-refund
        # escalation (general/security/etc.) in the same run - look it up
        # so the response actually carries ticket_id for this path too,
        # as documented in docs/API.md (previously only the refund
        # awaiting_approval path above did).
        ticket_result = await session.execute(
            select(SupportTicket).where(
                SupportTicket.tenant_id == tenant_id, SupportTicket.workflow_run_id == run.id
            )
        )
        existing_ticket = ticket_result.scalar_one_or_none()
        ticket_id = existing_ticket.id if existing_ticket is not None else None

    return {
        "workflow_run_id": run.id,
        "conversation_id": conversation_id,
        "status": "escalated" if requires_human else "resolved",
        "requires_human": requires_human,
        "response": result.get("final_response"),
        "ticket_id": ticket_id,
    }


async def resume_workflow(
    session: AsyncSession,
    *,
    tenant_id: str,
    workflow_run_id: str,
    approved: bool,
    approver: str,
    arguments_override: dict[str, Any] | None = None,
) -> dict:
    run = await session.get(WorkflowRun, workflow_run_id)
    if run is None:
        raise ValueError(f"Unknown workflow_run_id {workflow_run_id}")
    if run.tenant_id != tenant_id:
        # Never reveal whether the run exists in another tenant - same
        # error a missing run would produce (spec §43: no cross-tenant leak).
        raise AuthorizationError(f"Unknown workflow_run_id {workflow_run_id}")

    deps, _effective = await _build_deps(session, tenant_id)
    settings = get_settings()
    config: RunnableConfig = {
        "configurable": {"thread_id": run.id, "deps": deps},
        "metadata": {"conversation_id": run.conversation_id, "environment": settings.app_env},
        "tags": ["customer-support", "human-approval-resume", settings.app_env],
    }

    async with get_checkpointer() as checkpointer:
        graph = build_graph().compile(checkpointer=checkpointer)
        result = await graph.ainvoke(
            Command(resume={"approved": approved, "arguments_override": arguments_override}), config
        )

    requires_human_after_resume = bool(result.get("requires_human"))
    ticket_result = await session.execute(
        select(SupportTicket).where(SupportTicket.workflow_run_id == run.id)
    )
    ticket = ticket_result.scalar_one_or_none()
    if ticket is not None:
        # spec: Phase 8.2 - the real API/MCP response (or {"error": ...})
        # from an approved external-tool call, previously discarded after
        # being folded into resolution_facts/draft_response text. None for
        # a refund resume (human_approval_gate never sets this key for one).
        ticket.execution_result = result.get("execution_result")
        if approved and requires_human_after_resume:
            # The approved action itself failed during execution (e.g. an
            # MCP tool call error after approval, or a disabled/removed
            # integration - see app.workflow.nodes.human_approval) rather
            # than being rejected or completing cleanly. That's exactly
            # the kind of anomaly a human needs to see, not a ticket that
            # silently reads "resolved" while the customer got an apology.
            # Reopen it (rather than blindly marking resolved) so it stays
            # visible in the staff queue - see docs/API.md's ticket
            # lifecycle notes for why this doesn't also retry the call.
            ticket.status = "open"
            ticket.reason_for_escalation = result.get("escalation_reason") or ticket.reason_for_escalation
            # An approved action failing in production is more urgent than
            # a plain "I don't know" escalation - bump priority (never
            # down) so it doesn't get lost behind LOW/MEDIUM tickets in
            # the queue.
            current_rank = PRIORITY_ORDER.get(Priority(ticket.priority), 0)
            if current_rank < PRIORITY_ORDER[Priority.HIGH]:
                ticket.priority = Priority.HIGH.value
        else:
            ticket.status = "resolved" if approved else "rejected"
        ticket.approved_by = approver
        await session.flush()
    await session.commit()

    # Best-effort live nudge (spec: Phase 10.3's push, extended here) - a
    # ticket decision is exactly the case that push exists for: the
    # customer isn't the one who triggered this completion (a staff
    # member did, elsewhere), so without this they'd only find out via
    # the chat UI's own 5-second awaiting_approval poll. Additive
    # alongside the new assistant message `send_response` already
    # persisted during the graph's resumed run - never a replacement for
    # it, and a customer not currently connected simply doesn't get the
    # nudge.
    await get_connection_manager().broadcast(
        run.conversation_id,
        {"event": "ticket_decision", "workflow_run_id": run.id, "approved": approved},
    )

    return {
        "workflow_run_id": run.id,
        "conversation_id": run.conversation_id,
        "status": "escalated" if result.get("requires_human") else "resolved",
        "requires_human": bool(result.get("requires_human")),
        "response": result.get("final_response"),
    }
