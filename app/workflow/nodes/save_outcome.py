"""save_outcome node (spec §30): persists the workflow run outcome, updates
conversation status, and files a support ticket when escalating (§17).
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from app.agents.escalation import build_escalation_ticket
from app.domain.models import SupportTicket
from app.integrations.hooks import notify_ticket_created
from app.observability.metrics import FIRST_CONTACT_RESOLUTIONS
from app.repositories.conversations import ConversationRepository
from app.repositories.tickets import TicketRepository, WorkflowRepository
from app.workflow.deps import get_deps
from app.workflow.state import SupportState


async def save_outcome(state: SupportState, config: RunnableConfig) -> dict:
    deps = get_deps(config)
    tenant_id = state["tenant_id"]
    conversation_repo = ConversationRepository(deps.session, tenant_id)
    workflow_repo = WorkflowRepository(deps.session, tenant_id)

    requires_human = bool(state.get("requires_human"))
    status = "escalated" if requires_human else "resolved"

    conversation = await conversation_repo.get(state["conversation_id"])
    if conversation is not None:
        await conversation_repo.update_status(conversation, status)
        await conversation_repo.set_classification(
            conversation, intent=state.get("intent"), priority=state.get("priority")
        )

    run = await workflow_repo.get_run(state.get("workflow_run_id", ""))
    if run is not None:
        await workflow_repo.update_run(
            run,
            status=status,
            final_response=state.get("final_response"),
            requires_human=requires_human,
            response_confidence=state.get("response_confidence"),
            retry_count=state.get("retry_count", 0),
        )

    if requires_human:
        from sqlalchemy import select

        existing = await deps.session.execute(
            select(SupportTicket).where(
                SupportTicket.tenant_id == tenant_id,
                SupportTicket.workflow_run_id == state.get("workflow_run_id", ""),
            )
        )
        if existing.scalar_one_or_none() is not None:
            # Already filed when the workflow paused for approval (see
            # app.workflow.runner.run_workflow) - do not file a duplicate.
            await deps.session.commit()
            return {}

        ticket = build_escalation_ticket(
            conversation_id=state["conversation_id"],
            customer_id=state["customer_id"],
            workflow_run_id=state.get("workflow_run_id", ""),
            intent=(state.get("intent") or "UNKNOWN"),
            priority=(state.get("priority") or "MEDIUM"),
            latest_message=state["latest_message"],
            facts=state.get("resolution_facts", []),
            tool_calls=state.get("tool_calls", []),
            retrieved_documents=[d["title"] for d in state.get("retrieved_documents", [])],
            escalation_reason=state.get("escalation_reason") or "Escalation criteria met",
        )
        created_ticket = await TicketRepository(deps.session, tenant_id).create(
            SupportTicket(
                conversation_id=ticket.conversation_id,
                customer_id=ticket.customer_id,
                workflow_run_id=ticket.workflow_run_id,
                intent=ticket.intent,
                priority=ticket.priority,
                summary=ticket.summary,
                customer_problem=ticket.customer_problem,
                actions_taken=ticket.actions_taken,
                tools_used=ticket.tools_used,
                relevant_documents=ticket.relevant_documents,
                reason_for_escalation=ticket.reason_for_escalation,
                recommended_next_action=ticket.recommended_next_action,
            )
        )
        await notify_ticket_created(deps.session, tenant_id, created_ticket)
    else:
        FIRST_CONTACT_RESOLUTIONS.inc()

    await deps.session.commit()
    return {}
