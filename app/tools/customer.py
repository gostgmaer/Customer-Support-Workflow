from __future__ import annotations

import secrets

from pydantic import BaseModel

from app.domain.exceptions import ToolError
from app.repositories.conversations import ConversationRepository
from app.repositories.customers import CustomerRepository
from app.tools.base import ToolContext, run_tool


class GetCustomerProfileArgs(BaseModel):
    customer_id: str


class CustomerProfileResult(BaseModel):
    customer_id: str
    full_name: str
    email: str
    tier: str
    is_locked: bool


async def get_customer_profile(ctx: ToolContext, args: GetCustomerProfileArgs) -> CustomerProfileResult:
    async def _run() -> CustomerProfileResult:
        repo = CustomerRepository(ctx.session, ctx.tenant_id)
        customer = await repo.get(args.customer_id)
        if customer is None:
            raise ToolError(f"Customer {args.customer_id} not found")
        return CustomerProfileResult(
            customer_id=customer.id,
            full_name=customer.full_name,
            email=customer.email,
            tier=customer.tier,
            is_locked=customer.is_locked,
        )

    return await run_tool(
        ctx=ctx,
        tool_name="get_customer_profile",
        target_customer_id=args.customer_id,
        args=args,
        fn=_run,
    )


class ResetPasswordArgs(BaseModel):
    customer_id: str


class ResetPasswordResult(BaseModel):
    customer_id: str
    verification_sent: bool
    reset_token_last4: str


async def reset_password(ctx: ToolContext, args: ResetPasswordArgs) -> ResetPasswordResult:
    async def _run() -> ResetPasswordResult:
        repo = CustomerRepository(ctx.session, ctx.tenant_id)
        customer = await repo.get(args.customer_id)
        if customer is None:
            raise ToolError(f"Customer {args.customer_id} not found")
        token = secrets.token_hex(8)
        # In production this triggers a real email-verification flow instead
        # of resetting the password directly - the AI never has "limited"
        # (§12) direct-write access without customer confirmation.
        return ResetPasswordResult(
            customer_id=customer.id, verification_sent=True, reset_token_last4=token[-4:]
        )

    return await run_tool(
        ctx=ctx,
        tool_name="reset_password",
        target_customer_id=args.customer_id,
        args=args,
        fn=_run,
    )


class GetSupportHistoryArgs(BaseModel):
    customer_id: str
    conversation_id: str


class SupportHistoryResult(BaseModel):
    customer_id: str
    message_count: int
    recent_messages: list[str]


async def get_support_history(ctx: ToolContext, args: GetSupportHistoryArgs) -> SupportHistoryResult:
    async def _run() -> SupportHistoryResult:
        repo = ConversationRepository(ctx.session, ctx.tenant_id)
        messages = await repo.history(args.conversation_id)
        return SupportHistoryResult(
            customer_id=args.customer_id,
            message_count=len(messages),
            recent_messages=[m.content for m in messages[-5:]],
        )

    return await run_tool(
        ctx=ctx,
        tool_name="get_support_history",
        target_customer_id=args.customer_id,
        args=args,
        fn=_run,
    )
