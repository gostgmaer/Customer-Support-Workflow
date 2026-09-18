from __future__ import annotations

from pydantic import BaseModel

from app.config.policies import HIGH_RISK_REFUND_AMOUNT_USD
from app.domain.exceptions import ToolError
from app.domain.models import RefundRequest
from app.repositories.orders import OrderRepository, RefundRepository
from app.tools.base import ToolContext, run_tool


class CreateRefundRequestArgs(BaseModel):
    customer_id: str
    order_id: str
    amount: float
    reason: str
    idempotency_key: str
    customer_confirmed: bool


class RefundRequestResult(BaseModel):
    refund_id: str
    status: str
    amount: float
    requires_human_approval: bool
    replayed: bool = False


async def create_refund_request(ctx: ToolContext, args: CreateRefundRequestArgs) -> RefundRequestResult:
    async def _run() -> RefundRequestResult:
        if not args.customer_confirmed:
            raise ToolError("create_refund_request requires explicit customer confirmation")

        refund_repo = RefundRepository(ctx.session, ctx.tenant_id)
        existing = await refund_repo.get_by_idempotency_key(args.idempotency_key)
        if existing is not None:
            return RefundRequestResult(
                refund_id=existing.id,
                status=existing.status,
                amount=existing.amount,
                requires_human_approval=existing.amount >= HIGH_RISK_REFUND_AMOUNT_USD,
                replayed=True,
            )

        order_repo = OrderRepository(ctx.session, ctx.tenant_id)
        order = await order_repo.get(args.order_id)
        if order is None or order.customer_id != args.customer_id:
            raise ToolError(f"Order {args.order_id} not found for customer")
        if args.amount > order.total_amount:
            raise ToolError("Refund amount cannot exceed order total")

        requires_approval = args.amount >= HIGH_RISK_REFUND_AMOUNT_USD
        refund = await refund_repo.create(
            RefundRequest(
                order_id=args.order_id,
                customer_id=args.customer_id,
                amount=args.amount,
                status="pending",
                reason=args.reason,
                idempotency_key=args.idempotency_key,
            )
        )
        return RefundRequestResult(
            refund_id=refund.id,
            status=refund.status,
            amount=refund.amount,
            requires_human_approval=requires_approval,
        )

    return await run_tool(
        ctx=ctx,
        tool_name="create_refund_request",
        target_customer_id=args.customer_id,
        args=args,
        fn=_run,
        idempotency_key=args.idempotency_key,
    )


class GetRefundStatusArgs(BaseModel):
    customer_id: str
    order_id: str


class RefundStatusResult(BaseModel):
    refund_id: str
    status: str
    amount: float


async def get_refund_status(ctx: ToolContext, args: GetRefundStatusArgs) -> RefundStatusResult:
    async def _run() -> RefundStatusResult:
        refund_repo = RefundRepository(ctx.session, ctx.tenant_id)
        refund = await refund_repo.get_for_order(args.order_id)
        if refund is None or refund.customer_id != args.customer_id:
            raise ToolError(f"No refund found for order {args.order_id}")
        return RefundStatusResult(refund_id=refund.id, status=refund.status, amount=refund.amount)

    return await run_tool(
        ctx=ctx,
        tool_name="get_refund_status",
        target_customer_id=args.customer_id,
        args=args,
        fn=_run,
    )
