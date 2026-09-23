from __future__ import annotations

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.conversation import (
    ConversationResponse,
    CreateConversationRequest,
    MessageResponse,
)
from app.api.schemas.feedback import FeedbackResponse, SubmitFeedbackRequest
from app.api.schemas.support import SupportMessageRequest, SupportMessageResponse
from app.db.base import new_uuid
from app.db.session import get_db
from app.domain.exceptions import AuthenticationError, ValidationError
from app.domain.models import Conversation
from app.observability.metrics import REQUEST_COUNT, WORKFLOW_LATENCY
from app.realtime.connections import get_connection_manager
from app.repositories.conversations import ConversationRepository
from app.repositories.feedback import FeedbackRepository
from app.repositories.tickets import TicketRepository
from app.security.auth import decode_access_token, get_current_customer
from app.security.rate_limit import enforce_rate_limit
from app.workflow.runner import run_workflow

router = APIRouter(prefix="/api/v1/support", tags=["support"])


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    body: CreateConversationRequest,
    customer: tuple[str, str] = Depends(get_current_customer),
    session: AsyncSession = Depends(get_db),
) -> Conversation:
    customer_id, tenant_id = customer
    repo = ConversationRepository(session, tenant_id)
    conversation = await repo.get_or_create(new_uuid(), customer_id=customer_id, channel=body.channel.value)
    await session.commit()
    return conversation


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str,
    customer: tuple[str, str] = Depends(get_current_customer),
    session: AsyncSession = Depends(get_db),
) -> Conversation:
    customer_id, tenant_id = customer
    repo = ConversationRepository(session, tenant_id)
    conversation = await repo.get(conversation_id)
    if conversation is None or conversation.customer_id != customer_id:
        raise ValidationError(f"Conversation {conversation_id} not found")
    return conversation


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    conversation_id: str,
    customer: tuple[str, str] = Depends(get_current_customer),
    session: AsyncSession = Depends(get_db),
) -> list:
    customer_id, tenant_id = customer
    repo = ConversationRepository(session, tenant_id)
    conversation = await repo.get(conversation_id)
    if conversation is None or conversation.customer_id != customer_id:
        raise ValidationError(f"Conversation {conversation_id} not found")
    return await repo.history(conversation_id)


@router.post("/messages", response_model=SupportMessageResponse)
async def post_message(
    body: SupportMessageRequest,
    customer: tuple[str, str] = Depends(get_current_customer),
    session: AsyncSession = Depends(get_db),
) -> dict:
    customer_id, tenant_id = customer
    await enforce_rate_limit(f"messages:{tenant_id}:{customer_id}", session=session, tenant_id=tenant_id)
    with WORKFLOW_LATENCY.time():
        result = await run_workflow(
            session,
            tenant_id=tenant_id,
            conversation_id=body.conversation_id,
            customer_id=customer_id,
            message_id=body.message_id,
            message=body.message,
            channel=body.channel.value,
        )
    REQUEST_COUNT.labels(endpoint="post_message", status=result["status"]).inc()
    return {
        "conversation_id": result["conversation_id"],
        "workflow_run_id": result["workflow_run_id"],
        "status": result["status"],
        "response": result.get("response"),
        "requires_human": result["requires_human"],
        "ticket_id": result.get("ticket_id"),
    }


@router.post(
    "/conversations/{conversation_id}/feedback", response_model=FeedbackResponse, status_code=201
)
async def submit_feedback(
    conversation_id: str,
    body: SubmitFeedbackRequest,
    customer: tuple[str, str] = Depends(get_current_customer),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """spec: Phase 15 - CSAT. A customer may rate a conversation only once
    it has actually concluded: either its most recent ticket reached a
    terminal state (resolved/rejected - see app.workflow.runner.resume_workflow,
    the only place a ticket transitions there), or - for a conversation that
    never needed a ticket at all - the conversation itself is "resolved"
    (see app.workflow.nodes.save_outcome, the non-escalated path). Rating an
    open/awaiting_approval/escalated conversation is rejected, not silently
    accepted, so CSAT data always reflects an actual outcome."""
    customer_id, tenant_id = customer
    conversation_repo = ConversationRepository(session, tenant_id)
    conversation = await conversation_repo.get(conversation_id)
    if conversation is None or conversation.customer_id != customer_id:
        raise ValidationError(f"Conversation {conversation_id} not found")

    ticket = await TicketRepository(session, tenant_id).get_latest_for_conversation(conversation_id)
    eligible = (
        ticket.status in ("resolved", "rejected") if ticket is not None else conversation.status == "resolved"
    )
    if not eligible:
        raise ValidationError("Feedback can only be submitted for a resolved conversation")

    feedback_repo = FeedbackRepository(session, tenant_id)
    existing = await feedback_repo.get_for_conversation(conversation_id)
    if existing is not None:
        raise ValidationError("Feedback has already been submitted for this conversation")

    feedback = await feedback_repo.create(
        conversation_id=conversation_id, rating=body.rating, comment=body.comment, resolved=True
    )
    await session.commit()
    return {
        "id": feedback.id,
        "conversation_id": feedback.conversation_id,
        "rating": feedback.rating,
        "comment": feedback.comment,
        "resolved": feedback.resolved,
        "created_at": feedback.created_at,
    }


@router.websocket("/ws/conversations/{conversation_id}")
async def conversation_socket(
    websocket: WebSocket,
    conversation_id: str,
    token: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    """spec: Phase 10.3 - a best-effort live nudge for a customer actively
    looking at this conversation when the storefront webhook fires (see
    app.api.routes.webhooks's correlated branch). A browser `WebSocket`
    can't set a custom Authorization header, so the JWT travels as a
    query param and is decoded directly via `decode_access_token`,
    bypassing the `Header`-based `get_current_customer` dependency used
    by every HTTP route in this file. Server-push only: the receive loop
    exists purely to detect disconnect, not to read client messages."""
    try:
        customer_id, tenant_id = decode_access_token(token)
    except AuthenticationError:
        await websocket.close(code=4401)
        return

    repo = ConversationRepository(session, tenant_id)
    conversation = await repo.get(conversation_id)
    if conversation is None or conversation.customer_id != customer_id:
        await websocket.close(code=4404)
        return

    manager = get_connection_manager()
    await websocket.accept()
    await manager.register(conversation_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.unregister(conversation_id, websocket)
