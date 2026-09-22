from __future__ import annotations

from sqlalchemy import select

from app.domain.models import SupportTicket, ToolExecution, WorkflowEvent, WorkflowRun
from app.repositories.base import TenantScopedRepository


class TicketRepository(TenantScopedRepository):
    async def create(self, ticket: SupportTicket) -> SupportTicket:
        ticket.tenant_id = self.tenant_id
        self.session.add(ticket)
        await self.session.flush()
        return ticket

    async def get(self, ticket_id: str) -> SupportTicket | None:
        stmt = self._scope(select(SupportTicket).where(SupportTicket.id == ticket_id), SupportTicket)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        status: str | None = None,
        intent_filter: tuple[str, set[str]] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SupportTicket]:
        """`intent_filter` is `("include"|"exclude", intents)` from
        `app.config.policies.ticket_queue_filter_for_role` - scopes the
        queue to what the caller's role may act on (spec §36/§52)."""
        stmt = self._scope(select(SupportTicket), SupportTicket)
        if status is not None:
            stmt = stmt.where(SupportTicket.status == status)
        if intent_filter is not None:
            mode, intents = intent_filter
            condition = (
                SupportTicket.intent.in_(intents)
                if mode == "include"
                else SupportTicket.intent.notin_(intents)
            )
            stmt = stmt.where(condition)
        stmt = stmt.order_by(SupportTicket.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def set_status(
        self, ticket: SupportTicket, status: str, approved_by: str | None = None
    ) -> SupportTicket:
        ticket.status = status
        if approved_by:
            ticket.approved_by = approved_by
        await self.session.flush()
        return ticket


class WorkflowRepository(TenantScopedRepository):
    async def create_run(self, run: WorkflowRun) -> WorkflowRun:
        run.tenant_id = self.tenant_id
        self.session.add(run)
        await self.session.flush()
        return run

    async def get_run(self, run_id: str) -> WorkflowRun | None:
        stmt = self._scope(select(WorkflowRun).where(WorkflowRun.id == run_id), WorkflowRun)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_run(self, run: WorkflowRun, **fields) -> WorkflowRun:
        for key, value in fields.items():
            setattr(run, key, value)
        await self.session.flush()
        return run

    async def log_event(self, event: WorkflowEvent) -> WorkflowEvent:
        event.tenant_id = self.tenant_id
        self.session.add(event)
        await self.session.flush()
        return event

    async def log_tool_execution(self, execution: ToolExecution) -> ToolExecution:
        execution.tenant_id = self.tenant_id
        self.session.add(execution)
        await self.session.flush()
        return execution

    async def get_events(self, run_id: str) -> list[WorkflowEvent]:
        stmt = self._scope(
            select(WorkflowEvent).where(WorkflowEvent.workflow_run_id == run_id), WorkflowEvent
        ).order_by(WorkflowEvent.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_tool_executions(self, run_id: str) -> list[ToolExecution]:
        stmt = self._scope(
            select(ToolExecution).where(ToolExecution.workflow_run_id == run_id), ToolExecution
        ).order_by(ToolExecution.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
