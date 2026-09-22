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


class UpdateCustomerProfileArgs(BaseModel):
    customer_id: str
    new_full_name: str | None = None
    new_email: str | None = None
    customer_confirmed: bool


class UpdateCustomerProfileResult(BaseModel):
    customer_id: str
    full_name: str
    email: str
    updated_fields: list[str]


async def update_customer_profile(
    ctx: ToolContext, args: UpdateCustomerProfileArgs
) -> UpdateCustomerProfileResult:
    """spec: Phase 13 - name/email change. Always requires
    customer_confirmed (app.config.policies: ApprovalLevel.ALWAYS) AND, per
    the tool permission matrix, human staff approval before this ever runs
    (see app.workflow.nodes.human_approval) - identity-modifying, same tier
    as account unlock. Rejects a new_email already used by another customer
    in this tenant (Customer.email is globally unique at the DB level, but
    the clearer, tenant-scoped error belongs here, not a raw IntegrityError
    surfacing from the commit)."""

    async def _run() -> UpdateCustomerProfileResult:
        if not args.customer_confirmed:
            raise ToolError("update_customer_profile requires explicit customer confirmation")
        repo = CustomerRepository(ctx.session, ctx.tenant_id)
        customer = await repo.get(args.customer_id)
        if customer is None:
            raise ToolError(f"Customer {args.customer_id} not found")
        updated: list[str] = []
        if args.new_email and args.new_email != customer.email:
            existing = await repo.get_by_email(args.new_email)
            if existing is not None and existing.id != customer.id:
                raise ToolError(f"Email {args.new_email} is already in use")
            customer.email = args.new_email
            updated.append("email")
        if args.new_full_name and args.new_full_name != customer.full_name:
            customer.full_name = args.new_full_name
            updated.append("full_name")
        await ctx.session.flush()
        return UpdateCustomerProfileResult(
            customer_id=customer.id,
            full_name=customer.full_name,
            email=customer.email,
            updated_fields=updated,
        )

    return await run_tool(
        ctx=ctx,
        tool_name="update_customer_profile",
        target_customer_id=args.customer_id,
        args=args,
        fn=_run,
    )


class UnlockAccountArgs(BaseModel):
    customer_id: str
    customer_confirmed: bool


class UnlockAccountResult(BaseModel):
    customer_id: str
    unlocked: bool


async def unlock_account(ctx: ToolContext, args: UnlockAccountArgs) -> UnlockAccountResult:
    """spec: Phase 13 - `Customer.is_locked` existed on the model but no
    tool ever acted on it; ACCOUNT_ACCESS's resolver used to always offer a
    password reset regardless of lock state. Human-approved (security-
    relevant), same tier as update_customer_profile."""

    async def _run() -> UnlockAccountResult:
        if not args.customer_confirmed:
            raise ToolError("unlock_account requires explicit customer confirmation")
        repo = CustomerRepository(ctx.session, ctx.tenant_id)
        customer = await repo.get(args.customer_id)
        if customer is None:
            raise ToolError(f"Customer {args.customer_id} not found")
        customer.is_locked = False
        await ctx.session.flush()
        return UnlockAccountResult(customer_id=customer.id, unlocked=True)

    return await run_tool(
        ctx=ctx,
        tool_name="unlock_account",
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
