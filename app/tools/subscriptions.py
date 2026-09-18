from __future__ import annotations

from pydantic import BaseModel

from app.domain.exceptions import ToolError
from app.repositories.orders import SubscriptionRepository
from app.tools.base import ToolContext, run_tool


class GetSubscriptionArgs(BaseModel):
    customer_id: str


class SubscriptionResult(BaseModel):
    subscription_id: str
    plan: str
    status: str
    renews_at: str | None


async def get_subscription(ctx: ToolContext, args: GetSubscriptionArgs) -> SubscriptionResult:
    async def _run() -> SubscriptionResult:
        repo = SubscriptionRepository(ctx.session, ctx.tenant_id)
        sub = await repo.get_active_for_customer(args.customer_id)
        if sub is None:
            raise ToolError(f"No subscription found for customer {args.customer_id}")
        return SubscriptionResult(
            subscription_id=sub.id,
            plan=sub.plan,
            status=sub.status,
            renews_at=sub.renews_at.isoformat() if sub.renews_at else None,
        )

    return await run_tool(
        ctx=ctx, tool_name="get_subscription", target_customer_id=args.customer_id, args=args, fn=_run
    )


class UpdateSubscriptionArgs(BaseModel):
    customer_id: str
    new_status: str | None = None  # "cancelled" | "active"
    # spec: Phase 8.3 - an upgrade/downgrade, distinct from new_status.
    # Either field (or both) may be set; at least one is required.
    new_plan: str | None = None
    customer_confirmed: bool


class UpdateSubscriptionResult(BaseModel):
    subscription_id: str
    status: str
    plan: str


async def update_subscription(ctx: ToolContext, args: UpdateSubscriptionArgs) -> UpdateSubscriptionResult:
    async def _run() -> UpdateSubscriptionResult:
        if not args.customer_confirmed:
            raise ToolError("update_subscription requires explicit customer confirmation")
        if args.new_status is None and args.new_plan is None:
            raise ToolError("update_subscription requires new_status and/or new_plan")
        repo = SubscriptionRepository(ctx.session, ctx.tenant_id)
        sub = await repo.get_active_for_customer(args.customer_id)
        if sub is None:
            raise ToolError(f"No subscription found for customer {args.customer_id}")
        if args.new_status is not None:
            await repo.update_status(sub, args.new_status)
        if args.new_plan is not None:
            await repo.update_plan(sub, args.new_plan)
        return UpdateSubscriptionResult(subscription_id=sub.id, status=sub.status, plan=sub.plan)

    return await run_tool(
        ctx=ctx,
        tool_name="update_subscription",
        target_customer_id=args.customer_id,
        args=args,
        fn=_run,
    )
