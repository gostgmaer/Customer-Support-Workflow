"""Shared tool-execution scaffolding (spec §10-11).

Every tool call goes through `run_tool`, which enforces: authorization
(ownership + permission matrix), input validation (Pydantic args model),
retry-on-transient-failure, audit logging, and PII redaction of what gets
persisted/logged. Tools never let the LLM construct free-form queries -
each tool takes a strict, typed argument model (see e.g. GetOrderArgs).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import ToolError
from app.domain.models import ToolExecution
from app.observability.logging import get_logger
from app.observability.metrics import TOOL_LATENCY, TOOL_SUCCESS
from app.observability.retry import with_retry
from app.security.authorization import authorize_tool_call
from app.security.pii import redact_dict

logger = get_logger(__name__)

ArgsT = TypeVar("ArgsT", bound=BaseModel)
ResultT = TypeVar("ResultT", bound=BaseModel)


@dataclass
class ToolContext:
    session: AsyncSession
    requesting_customer_id: str
    workflow_run_id: str
    tenant_id: str


async def run_tool(
    *,
    ctx: ToolContext,
    tool_name: str,
    target_customer_id: str,
    args: BaseModel,
    fn: Callable[[], Awaitable[ResultT]],
    idempotency_key: str | None = None,
) -> ResultT:
    authorize_tool_call(
        tool_name=tool_name,
        requesting_customer_id=ctx.requesting_customer_id,
        target_customer_id=target_customer_id,
    )

    start = time.perf_counter()
    success = False
    result: Any = None
    try:
        result = await with_retry(fn)
        success = True
        return result
    except Exception as exc:  # noqa: BLE001
        logger.error("tool_execution_failed", tool_name=tool_name, error=str(exc))
        if not isinstance(exc, ToolError):
            exc = ToolError(f"{tool_name} failed: {exc}")
        raise exc
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        TOOL_LATENCY.labels(tool_name=tool_name).observe(duration_ms / 1000)
        TOOL_SUCCESS.labels(tool_name=tool_name, outcome="success" if success else "failure").inc()
        result_summary = redact_dict(result.model_dump()) if isinstance(result, BaseModel) else {}
        ctx.session.add(
            ToolExecution(
                tenant_id=ctx.tenant_id,
                workflow_run_id=ctx.workflow_run_id,
                customer_id=target_customer_id,
                tool_name=tool_name,
                arguments=redact_dict(args.model_dump()),
                result_summary=result_summary,
                success=success,
                duration_ms=duration_ms,
                idempotency_key=idempotency_key,
            )
        )
        await ctx.session.flush()
