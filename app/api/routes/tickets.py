from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.ticket import ApproveTicketRequest, RejectTicketRequest, TicketResponse
from app.config.policies import roles_allowed_to_approve, ticket_queue_filter_for_role
from app.db.base import new_uuid
from app.db.session import get_db
from app.domain.exceptions import AuthorizationError, ValidationError
from app.domain.models import SupportTicket
from app.integrations.hooks import create_jira_issue_for_ticket, notify_ticket_decision
from app.repositories.audit import AuditRepository
from app.repositories.tickets import TicketRepository
from app.security.auth import STAFF_ROLES, require_staff_role
from app.workflow.runner import resume_workflow

router = APIRouter(prefix="/api/v1/support/tickets", tags=["tickets"])

RequireAnyStaff = Depends(require_staff_role(*STAFF_ROLES))


def _require_role_for_ticket(ticket: SupportTicket, role: str) -> None:
    """spec §36/§52: SECURITY/FRAUD/LEGAL tickets are a restricted queue -
    only SECURITY_AGENT/ADMIN may act on them, regardless of which staff
    role is otherwise allowed to approve/reject tickets in general."""
    allowed = roles_allowed_to_approve(ticket.intent)
    if role not in allowed:
        raise AuthorizationError(
            f"Role '{role}' cannot act on a '{ticket.intent}' ticket - requires one of {allowed}"
        )


@router.get("", response_model=list[TicketResponse])
async def list_tickets(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
    staff: tuple[str, str, str] = RequireAnyStaff,
) -> list[SupportTicket]:
    """The staff ticket queue (spec §36/§52): automatically scoped to the
    caller's role - a SUPPORT_AGENT/SUPPORT_MANAGER never sees a
    SECURITY/FRAUD/LEGAL ticket in their queue at all, a SECURITY_AGENT
    sees only those, and ADMIN sees everything - see
    `app.config.policies.ticket_queue_filter_for_role`."""
    _staff_id, role, tenant_id = staff
    return await TicketRepository(session, tenant_id).list(
        status=status, intent_filter=ticket_queue_filter_for_role(role), limit=limit, offset=offset
    )


@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: str,
    session: AsyncSession = Depends(get_db),
    staff: tuple[str, str, str] = RequireAnyStaff,
) -> SupportTicket:
    _staff_id, role, tenant_id = staff
    ticket = await TicketRepository(session, tenant_id).get(ticket_id)
    if ticket is None:
        raise ValidationError(f"Ticket {ticket_id} not found")
    _require_role_for_ticket(ticket, role)
    return ticket


@router.post("/{ticket_id}/approve", response_model=TicketResponse)
async def approve_ticket(
    ticket_id: str,
    body: ApproveTicketRequest,
    session: AsyncSession = Depends(get_db),
    staff: tuple[str, str, str] = RequireAnyStaff,
) -> SupportTicket:
    staff_id, role, tenant_id = staff
    ticket_repo = TicketRepository(session, tenant_id)
    ticket = await ticket_repo.get(ticket_id)
    if ticket is None:
        raise ValidationError(f"Ticket {ticket_id} not found")
    _require_role_for_ticket(ticket, role)
    if ticket.status != "open":
        raise ValidationError(f"Ticket {ticket_id} is not awaiting approval (status={ticket.status})")

    await resume_workflow(
        session,
        tenant_id=tenant_id,
        workflow_run_id=body.workflow_run_id,
        approved=True,
        approver=staff_id,
        arguments_override=body.arguments,
    )
    await AuditRepository(session, tenant_id).record(
        actor=f"human:{staff_id}",
        action="approve_ticket",
        resource_type="support_ticket",
        resource_id=ticket_id,
        outcome="success",
        correlation_id=body.workflow_run_id or new_uuid(),
    )
    await notify_ticket_decision(session, tenant_id, ticket, approved=True, staff_id=staff_id, reason="")
    await session.commit()
    refreshed = await ticket_repo.get(ticket_id)
    return refreshed  # type: ignore[return-value]


@router.post("/{ticket_id}/reject", response_model=TicketResponse)
async def reject_ticket(
    ticket_id: str,
    body: RejectTicketRequest,
    session: AsyncSession = Depends(get_db),
    staff: tuple[str, str, str] = RequireAnyStaff,
) -> SupportTicket:
    staff_id, role, tenant_id = staff
    ticket_repo = TicketRepository(session, tenant_id)
    ticket = await ticket_repo.get(ticket_id)
    if ticket is None:
        raise ValidationError(f"Ticket {ticket_id} not found")
    _require_role_for_ticket(ticket, role)
    if ticket.status != "open":
        raise ValidationError(f"Ticket {ticket_id} is not awaiting approval (status={ticket.status})")

    await resume_workflow(
        session,
        tenant_id=tenant_id,
        workflow_run_id=body.workflow_run_id,
        approved=False,
        approver=staff_id,
    )
    await AuditRepository(session, tenant_id).record(
        actor=f"human:{staff_id}",
        action="reject_ticket",
        resource_type="support_ticket",
        resource_id=ticket_id,
        outcome="success",
        correlation_id=body.workflow_run_id or new_uuid(),
        details={"reason": body.reason} if body.reason else {},
    )
    await notify_ticket_decision(
        session, tenant_id, ticket, approved=False, staff_id=staff_id, reason=body.reason
    )
    await session.commit()
    refreshed = await ticket_repo.get(ticket_id)
    return refreshed  # type: ignore[return-value]


@router.post("/{ticket_id}/jira", response_model=TicketResponse)
async def create_jira_issue_route(
    ticket_id: str,
    session: AsyncSession = Depends(get_db),
    staff: tuple[str, str, str] = RequireAnyStaff,
) -> SupportTicket:
    """Manual fallback for the JIRA auto-create hook (spec: staff can push
    a ticket to JIRA on demand - e.g. it wasn't configured yet, or the
    automatic attempt failed). Unlike the automatic path, failures here
    are NOT swallowed - a staff member clicking "Create in JIRA" needs to
    know if it didn't work, not see a silent no-op."""
    _staff_id, role, tenant_id = staff
    ticket_repo = TicketRepository(session, tenant_id)
    ticket = await ticket_repo.get(ticket_id)
    if ticket is None:
        raise ValidationError(f"Ticket {ticket_id} not found")
    _require_role_for_ticket(ticket, role)

    if not ticket.external_ref:
        used = await create_jira_issue_for_ticket(session, tenant_id, ticket)
        if not used:
            raise ValidationError("No enabled JIRA integration is configured for this tenant")
        await session.commit()
    return ticket
