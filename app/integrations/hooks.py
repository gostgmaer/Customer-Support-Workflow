"""Deterministic (non-LLM) integration triggers, called from the workflow
and ticket-decision code paths. Every function here swallows its own
errors and logs a warning instead of raising - an external system being
down or misconfigured must never break a ticket's core lifecycle. This is
the opposite of app.llm's failover policy on purpose: LLM failures are
central to correctness (spec §6), integration failures are best-effort
side effects.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import SupportTicket
from app.integrations.email import EmailClient
from app.integrations.jira import JiraClient
from app.observability.logging import get_logger
from app.repositories.customers import CustomerRepository
from app.repositories.integrations import IntegrationRepository

logger = get_logger(__name__)


async def create_jira_issue_for_ticket(session: AsyncSession, tenant_id: str, ticket: SupportTicket) -> bool:
    """Raising core of the JIRA auto-create behavior - used directly by the
    manual `POST /support/tickets/{id}/jira` endpoint (spec: staff should
    see *why* a manual retry failed, not have it silently swallowed).
    Returns False (not an error) if this tenant has no enabled JIRA
    integration; raises `IntegrationError` if one exists but the call
    fails. Sets `ticket.external_ref`/`external_url` on success - the
    caller is responsible for flushing/committing."""
    integration = await IntegrationRepository(session, tenant_id).get_enabled_by_type("jira")
    if integration is None:
        return False
    result = await JiraClient(integration).create_issue(
        summary=ticket.summary or f"{ticket.intent} escalation",
        description=(
            f"{ticket.customer_problem}\n\nReason for escalation: {ticket.reason_for_escalation}\n\n"
            f"(Filed automatically by the support workflow - ticket {ticket.id})"
        ),
        priority=ticket.priority,
    )
    ticket.external_ref = result["key"]
    ticket.external_url = result["url"]
    await session.flush()
    return True


async def notify_ticket_created(session: AsyncSession, tenant_id: str, ticket: SupportTicket) -> None:
    """Fail-open wrapper around `create_jira_issue_for_ticket` for the
    *automatic* path (ticket escalation) - an external system being down
    must never break the workflow itself (see module docstring)."""
    try:
        if await create_jira_issue_for_ticket(session, tenant_id, ticket):
            logger.info("jira_issue_auto_created", ticket_id=ticket.id, jira_key=ticket.external_ref)
    except Exception as exc:  # noqa: BLE001
        logger.warning("jira_auto_create_failed", ticket_id=ticket.id, error=str(exc))


async def notify_ticket_decision(
    session: AsyncSession,
    tenant_id: str,
    ticket: SupportTicket,
    *,
    approved: bool,
    staff_id: str,
    reason: str,
) -> None:
    """Posts the approve/reject decision back to JIRA (if this ticket has
    an external_ref) and emails the customer (if an SMTP integration is
    configured) - both best-effort, see module docstring."""
    decision = "approved" if approved else "rejected"

    if ticket.external_ref:
        try:
            integration = await IntegrationRepository(session, tenant_id).get_enabled_by_type("jira")
            if integration is not None:
                comment = f"Ticket {decision} by {staff_id}."
                if reason:
                    comment += f" Reason: {reason}"
                await JiraClient(integration).add_comment(ticket.external_ref, comment)
        except Exception as exc:  # noqa: BLE001
            logger.warning("jira_comment_failed", ticket_id=ticket.id, error=str(exc))

    try:
        integration = await IntegrationRepository(session, tenant_id).get_enabled_by_type("smtp")
        if integration is None:
            return
        customer = await CustomerRepository(session, tenant_id).get(ticket.customer_id)
        if customer is None:
            return
        subject = f"Update on your support request ({decision})"
        body = (
            f"Hi {customer.full_name},\n\n"
            f"Your support request has been {decision} by our team.\n\n"
            f"{('Reason: ' + reason) if reason and not approved else ''}\n\n"
            "If you have any questions, just reply to this conversation in the app."
        )
        await EmailClient(integration).send(to=customer.email, subject=subject, body=body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("customer_email_failed", ticket_id=ticket.id, error=str(exc))
