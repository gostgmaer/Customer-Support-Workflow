"""Inbound webhooks (spec: Phase 8.4 storefront events, extended in
Phase 9.4 for Stripe).

Along with `/stripe/{integration_id}` below, the only inbound-
authenticated routes in this codebase - every other integration is this
app calling OUT (JIRA/WooCommerce/MCP/OpenAPI/email/Stripe's own REST
API). No staff JWT here: the caller is an external system, authenticated
by a signature keyed on `Integration.config.webhook_secret`
(`app.security.webhooks.verify_webhook_signature` for the storefront
route, `verify_stripe_signature` for Stripe's own signing scheme - both
now share the same `t=<timestamp>,v1=<hex>` wire format and replay-
protection posture as of Phase 10.1, but stay separate functions) rather
than a bearer token.

Scoped as an honest MVP, not a full event-driven rearchitecture - see
docs/ARCHITECTURE.md's "Inbound storefront webhooks" for the full
reasoning: this never tries to resume or inject into an existing
LangGraph run (app.workflow.runner.resume_workflow only ever accepts a
bool approval against one specific thread_id - there's no clean seam to
push an arbitrary new event into a paused or already-finished run).
Instead, a webhook event either correlates to a real, existing
`Conversation` (best-effort, via `Conversation.metadata_json["last_order_id"]`
- see app.agents.resolution.resolve_via_storefront) and becomes a new,
low-priority informational `SupportTicket` on it, or - since
`SupportTicket`/`Conversation` both require a real customer_id and this
event carries none - it's acknowledged (200) and logged, not force-fit
into a ticket with no real owner.

On a correlation hit (spec: Phase 10.3), a best-effort live nudge is
also pushed over `app.realtime.connections`' websocket registry to any
browser tab currently connected to that conversation - purely additive
UX on top of the ticket above, which stays the durable, staff-visible
record regardless of whether anyone was connected to receive the push.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.domain.exceptions import AuthenticationError
from app.domain.models import Conversation, Integration, SupportTicket
from app.observability.logging import get_logger
from app.realtime.connections import get_connection_manager
from app.repositories.orders import PaymentRepository, RefundRepository
from app.security.webhooks import verify_stripe_signature, verify_webhook_signature

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

# Most-recently-updated conversations scanned for a metadata_json
# correlation match - a full index/JSON-query approach would need
# dialect-specific SQL (Postgres `->>` vs SQLite `json_extract`, neither
# of which this codebase uses anywhere else) for a best-effort feature;
# an in-Python scan over a bounded recent window is simpler and correct
# at this app's scale.
_CORRELATION_SCAN_LIMIT = 200


class StorefrontWebhookPayload(BaseModel):
    event: str = Field(min_length=1, max_length=100)
    order_id: str = Field(min_length=1, max_length=100)
    data: dict[str, Any] = Field(default_factory=dict)


async def _find_conversation_by_order_id(
    session: AsyncSession, tenant_id: str, order_id: str
) -> Conversation | None:
    stmt = (
        select(Conversation)
        .where(Conversation.tenant_id == tenant_id)
        .order_by(Conversation.updated_at.desc())
        .limit(_CORRELATION_SCAN_LIMIT)
    )
    result = await session.execute(stmt)
    for conversation in result.scalars():
        if conversation.metadata_json.get("last_order_id") == order_id:
            return conversation
    return None


@router.post("/storefront/{integration_id}", status_code=200)
async def receive_storefront_webhook(
    integration_id: str,
    request: Request,
    x_webhook_signature: str = Header(default=""),
    session: AsyncSession = Depends(get_db),
) -> dict:
    # A cross-tenant lookup by primary key, deliberately - the caller has
    # no tenant concept, only the integration_id it was configured with.
    # Same "don't reveal whether the id exists at all" posture as
    # app.workflow.runner.resume_workflow's cross-tenant workflow_run_id
    # check: a missing/disabled/unconfigured integration and a bad
    # signature all return the exact same 401, never a distinguishable
    # 404 that would let a caller enumerate valid integration ids.
    integration = await session.get(Integration, integration_id)
    body = await request.body()
    secret = (integration.config.get("webhook_secret") if integration else None) or ""
    if (
        integration is None
        or not integration.enabled
        or not verify_webhook_signature(body, x_webhook_signature, secret)
    ):
        raise AuthenticationError("Invalid or unauthorized webhook request")

    payload = StorefrontWebhookPayload.model_validate_json(body)
    logger.info(
        "storefront_webhook_received",
        integration_id=integration.id,
        webhook_event=payload.event,
        order_id=payload.order_id,
    )

    conversation = await _find_conversation_by_order_id(session, integration.tenant_id, payload.order_id)
    if conversation is None:
        logger.info(
            "storefront_webhook_uncorrelated",
            integration_id=integration.id,
            order_id=payload.order_id,
        )
        return {"received": True, "correlated": False}

    ticket = SupportTicket(
        tenant_id=integration.tenant_id,
        conversation_id=conversation.id,
        customer_id=conversation.customer_id,
        workflow_run_id=None,
        intent="WEBHOOK",
        priority="LOW",
        status="open",
        summary=f"Storefront event: {payload.event} for order {payload.order_id}",
        customer_problem=f"(Received from {integration.name}, not from the customer)",
        actions_taken=[],
        tools_used=[],
        relevant_documents=[],
        reason_for_escalation=f"Inbound {payload.event} event from the connected storefront",
    )
    session.add(ticket)
    await session.commit()

    # Best-effort live nudge (spec: Phase 10.3) - additive alongside the
    # durable ticket above, never a replacement for it. A customer not
    # currently connected simply doesn't get this; the ticket is the
    # real, staff-visible record regardless.
    await get_connection_manager().broadcast(
        conversation.id,
        {"event": payload.event, "order_id": payload.order_id, "ticket_id": ticket.id},
    )

    return {"received": True, "correlated": True, "ticket_id": ticket.id}


class StripeWebhookEvent(BaseModel):
    """A real Stripe event envelope is much larger than this - only the
    fields this handler actually reads are modeled, matching this
    codebase's existing preference (see StorefrontWebhookPayload above)
    for not over-specifying a payload shape beyond what's used."""

    id: str
    type: str
    data: dict[str, Any] = Field(default_factory=dict)


# Real Stripe PaymentIntent statuses this app treats as "the retry
# resolved successfully" - see app.tools.payments's identical constant
# for why every other real status maps to "failed" rather than being
# enumerated individually.
_STRIPE_PAYMENT_SUCCESS_STATUSES = {"succeeded"}


@router.post("/stripe/{integration_id}", status_code=200)
async def receive_stripe_webhook(
    integration_id: str,
    request: Request,
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Stripe's own webhook signing scheme (spec: Phase 9.4) - real
    Stripe API responses are provisional, this webhook is the
    authoritative confirmation of what actually happened, which is why
    `app.workflow.nodes.human_approval`'s synchronous refund call never
    marks a `RefundRequest` `"completed"` itself - only this route does,
    once Stripe confirms it. Same cross-tenant-lookup / no-distinguishable-404
    posture as the storefront route above."""
    integration = await session.get(Integration, integration_id)
    body = await request.body()
    secret = (integration.config.get("webhook_secret") if integration else None) or ""
    if (
        integration is None
        or not integration.enabled
        or not verify_stripe_signature(body, stripe_signature, secret)
    ):
        raise AuthenticationError("Invalid or unauthorized webhook request")

    event = StripeWebhookEvent.model_validate_json(body)
    obj = event.data.get("object", {}) if isinstance(event.data.get("object"), dict) else {}
    logger.info(
        "stripe_webhook_received", integration_id=integration.id, event_type=event.type, event_id=event.id
    )
    tenant_id = integration.tenant_id

    if event.type in {"payment_intent.succeeded", "payment_intent.payment_failed"}:
        payment_repo = PaymentRepository(session, tenant_id)
        payment = await payment_repo.get_by_gateway_payment_intent_id(obj.get("id", ""))
        if payment is not None:
            new_status = "succeeded" if obj.get("status") in _STRIPE_PAYMENT_SUCCESS_STATUSES else "failed"
            await payment_repo.update_status(payment, new_status)
            await session.commit()
        return {"received": True, "handled": payment is not None}

    if event.type == "refund.updated":
        refund_repo = RefundRepository(session, tenant_id)
        refund = await refund_repo.get_by_gateway_reference(obj.get("id", ""))
        if refund is not None and obj.get("status") == "succeeded":
            await refund_repo.update_status(refund, "completed")
            await session.commit()
        return {"received": True, "handled": refund is not None}

    return {"received": True, "handled": False}
