"""load_conversation node (spec §4, §30).

Ensures the conversation/message rows exist, loads recent history, and
builds a minimal `customer_context` (never the full raw customer record -
spec: "Do not place unnecessary sensitive customer data inside the LLM
state").
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from app.domain.exceptions import ToolError
from app.observability.logging import bind_context
from app.repositories.conversations import ConversationRepository
from app.security.pii import redact
from app.tools import customer as customer_tools
from app.tools.base import ToolContext
from app.workflow.deps import get_deps
from app.workflow.state import SupportState


async def load_conversation(state: SupportState, config: RunnableConfig) -> dict:
    deps = get_deps(config)
    bind_context(
        conversation_id=state["conversation_id"],
        customer_id=state["customer_id"],
        workflow_run_id=state.get("workflow_run_id"),
    )

    repo = ConversationRepository(deps.session, state["tenant_id"])
    conversation = await repo.get_or_create(
        state["conversation_id"], customer_id=state["customer_id"], channel=state.get("channel", "web")
    )
    await repo.add_message(
        conversation_id=conversation.id, role="customer", content=state["latest_message"]
    )
    history = await repo.history(conversation.id)
    history_dicts = [
        {"role": "user" if m.role == "customer" else m.role, "content": redact(m.content)}
        for m in history
    ]

    customer_context: dict = {"customer_id": state["customer_id"]}
    ctx = ToolContext(
        session=deps.session,
        requesting_customer_id=state["customer_id"],
        workflow_run_id=state.get("workflow_run_id", ""),
        tenant_id=state["tenant_id"],
    )
    try:
        profile = await customer_tools.get_customer_profile(
            ctx, customer_tools.GetCustomerProfileArgs(customer_id=state["customer_id"])
        )
        customer_context.update(tier=profile.tier, is_locked=profile.is_locked)
    except ToolError:
        customer_context["profile_lookup_failed"] = True

    return {
        "messages": history_dicts,
        "customer_context": customer_context,
        "previous_intent": conversation.intent,
    }
