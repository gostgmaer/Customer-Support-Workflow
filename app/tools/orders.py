from __future__ import annotations

from pydantic import BaseModel

from app.domain.exceptions import ToolError
from app.repositories.orders import OrderRepository
from app.tools.base import ToolContext, run_tool


class GetOrderArgs(BaseModel):
    customer_id: str
    order_id: str


class OrderResult(BaseModel):
    order_id: str
    status: str
    total_amount: float
    currency: str
    product_name: str
    placed_at: str


async def get_order(ctx: ToolContext, args: GetOrderArgs) -> OrderResult:
    async def _run() -> OrderResult:
        repo = OrderRepository(ctx.session, ctx.tenant_id)
        order = await repo.get(args.order_id)
        if order is None or order.customer_id != args.customer_id:
            raise ToolError(f"Order {args.order_id} not found for customer")
        return OrderResult(
            order_id=order.id,
            status=order.status,
            total_amount=order.total_amount,
            currency=order.currency,
            product_name=order.product_name,
            placed_at=order.placed_at.isoformat(),
        )

    return await run_tool(
        ctx=ctx, tool_name="get_order", target_customer_id=args.customer_id, args=args, fn=_run
    )


class GetOrderHistoryArgs(BaseModel):
    customer_id: str
    limit: int = 10


class OrderHistoryResult(BaseModel):
    orders: list[OrderResult]


async def get_order_history(ctx: ToolContext, args: GetOrderHistoryArgs) -> OrderHistoryResult:
    async def _run() -> OrderHistoryResult:
        repo = OrderRepository(ctx.session, ctx.tenant_id)
        orders = await repo.list_for_customer(args.customer_id, limit=args.limit)
        return OrderHistoryResult(
            orders=[
                OrderResult(
                    order_id=o.id,
                    status=o.status,
                    total_amount=o.total_amount,
                    currency=o.currency,
                    product_name=o.product_name,
                    placed_at=o.placed_at.isoformat(),
                )
                for o in orders
            ]
        )

    return await run_tool(
        ctx=ctx,
        tool_name="get_order_history",
        target_customer_id=args.customer_id,
        args=args,
        fn=_run,
    )


class GetShippingStatusArgs(BaseModel):
    customer_id: str
    order_id: str


class ShippingStatusResult(BaseModel):
    order_id: str
    status: str
    carrier: str
    tracking_number: str
    estimated_delivery: str | None


async def get_shipping_status(ctx: ToolContext, args: GetShippingStatusArgs) -> ShippingStatusResult:
    async def _run() -> ShippingStatusResult:
        repo = OrderRepository(ctx.session, ctx.tenant_id)
        order = await repo.get(args.order_id)
        if order is None or order.customer_id != args.customer_id:
            raise ToolError(f"Order {args.order_id} not found for customer")
        return ShippingStatusResult(
            order_id=order.id,
            status=order.status,
            carrier=order.carrier,
            tracking_number=order.tracking_number,
            estimated_delivery=order.estimated_delivery.isoformat() if order.estimated_delivery else None,
        )

    return await run_tool(
        ctx=ctx,
        tool_name="get_shipping_status",
        target_customer_id=args.customer_id,
        args=args,
        fn=_run,
    )


class CancelOrderArgs(BaseModel):
    customer_id: str
    order_id: str
    customer_confirmed: bool


class CancelOrderResult(BaseModel):
    order_id: str
    cancelled: bool
    reason: str = ""


NON_CANCELLABLE_STATUSES = {"shipped", "in_transit", "delivered", "cancelled"}


async def cancel_order(ctx: ToolContext, args: CancelOrderArgs) -> CancelOrderResult:
    async def _run() -> CancelOrderResult:
        if not args.customer_confirmed:
            raise ToolError("cancel_order requires explicit customer confirmation")
        repo = OrderRepository(ctx.session, ctx.tenant_id)
        order = await repo.get(args.order_id)
        if order is None or order.customer_id != args.customer_id:
            raise ToolError(f"Order {args.order_id} not found for customer")
        if order.status in NON_CANCELLABLE_STATUSES:
            return CancelOrderResult(
                order_id=order.id,
                cancelled=False,
                reason=f"Order already {order.status}; cannot cancel.",
            )
        await repo.update_status(order, "cancelled")
        return CancelOrderResult(order_id=order.id, cancelled=True)

    return await run_tool(
        ctx=ctx, tool_name="cancel_order", target_customer_id=args.customer_id, args=args, fn=_run
    )


# spec: Phase 8.3 - a shipped/in-transit/delivered order's fulfillment can
# no longer be redirected (the package is already moving/arrived).
# Consulted by app.agents.resolution.resolve_address_change, which
# deliberately has no way to actually change the address internally (see
# that function's docstring for why) - this constant only gates the one
# deterministic thing that resolver CAN safely say without parsing a
# full mailing address out of free text.
NON_ADDRESS_CHANGEABLE_STATUSES = {"shipped", "in_transit", "delivered"}
