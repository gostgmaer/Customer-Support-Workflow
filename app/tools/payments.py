from __future__ import annotations

from pydantic import BaseModel

from app.domain.exceptions import IntegrationError, ToolError
from app.integrations.stripe import StripeClient
from app.repositories.integrations import IntegrationRepository
from app.repositories.orders import PaymentRepository
from app.tools.base import ToolContext, run_tool

# spec: Phase 9.4b - a real Stripe PaymentIntent that confirms
# successfully reports one of these statuses; every other real status
# (requires_action/requires_capture/processing/canceled/etc.) means the
# retry did not resolve to a successful charge - mapped to "failed" here
# rather than enumerated individually, since this app's own Payment.status
# column only ever distinguishes succeeded/failed/pending/refunded.
_STRIPE_SUCCESS_STATUSES = {"succeeded"}


class GetPaymentStatusArgs(BaseModel):
    customer_id: str
    order_id: str


class PaymentStatusResult(BaseModel):
    order_id: str
    status: str
    amount: float
    failure_reason: str = ""


async def get_payment_status(ctx: ToolContext, args: GetPaymentStatusArgs) -> PaymentStatusResult:
    async def _run() -> PaymentStatusResult:
        repo = PaymentRepository(ctx.session, ctx.tenant_id)
        payment = await repo.get_latest_for_order(args.order_id)
        if payment is None or payment.customer_id != args.customer_id:
            raise ToolError(f"No payment found for order {args.order_id}")
        return PaymentStatusResult(
            order_id=args.order_id,
            status=payment.status,
            amount=payment.amount,
            failure_reason=payment.failure_reason,
        )

    return await run_tool(
        ctx=ctx,
        tool_name="get_payment_status",
        target_customer_id=args.customer_id,
        args=args,
        fn=_run,
    )


class RetryPaymentArgs(BaseModel):
    customer_id: str
    order_id: str
    customer_confirmed: bool


class RetryPaymentResult(BaseModel):
    order_id: str
    status: str
    retried: bool
    reason: str = ""


# spec: Phase 8.3, extended in Phase 9.4b - this app has no real payment
# gateway configured by default (see app.tools.refunds's equivalent
# note), so a "retry" is a status-only simulation: a failed payment
# moves to "succeeded", anything else is left untouched and reported as
# not retried. When a tenant HAS an enabled `stripe` integration and this
# payment carries a `gateway_payment_intent_id`, the retry instead
# confirms the real PaymentIntent through Stripe and maps its real
# status back - the simulation is the fallback, not the only path.
async def retry_payment(ctx: ToolContext, args: RetryPaymentArgs) -> RetryPaymentResult:
    async def _run() -> RetryPaymentResult:
        if not args.customer_confirmed:
            raise ToolError("retry_payment requires explicit customer confirmation")
        repo = PaymentRepository(ctx.session, ctx.tenant_id)
        payment = await repo.get_latest_for_order(args.order_id)
        if payment is None or payment.customer_id != args.customer_id:
            raise ToolError(f"No payment found for order {args.order_id}")
        if payment.status != "failed":
            return RetryPaymentResult(
                order_id=args.order_id,
                status=payment.status,
                retried=False,
                reason=f"Payment is already '{payment.status}'; nothing to retry.",
            )

        stripe_integration = await IntegrationRepository(ctx.session, ctx.tenant_id).get_enabled_by_type(
            "stripe"
        )
        if stripe_integration is not None and payment.gateway_payment_intent_id:
            try:
                result = await StripeClient(stripe_integration).confirm_payment_intent(
                    payment.gateway_payment_intent_id
                )
            except IntegrationError as exc:
                raise ToolError(f"Stripe payment retry failed: {exc}") from exc
            new_status = "succeeded" if result.get("status") in _STRIPE_SUCCESS_STATUSES else "failed"
            await repo.update_status(payment, new_status)
            return RetryPaymentResult(order_id=args.order_id, status=new_status, retried=True)

        await repo.update_status(payment, "succeeded")
        return RetryPaymentResult(order_id=args.order_id, status="succeeded", retried=True)

    return await run_tool(
        ctx=ctx,
        tool_name="retry_payment",
        target_customer_id=args.customer_id,
        args=args,
        fn=_run,
    )
