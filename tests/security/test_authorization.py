import pytest

from app.db.base import DEFAULT_TENANT_ID
from app.domain.exceptions import AuthorizationError
from app.tools import orders as order_tools
from app.tools.base import ToolContext


@pytest.mark.asyncio
async def test_cannot_access_another_customers_order(db_session, seeded_customer, seeded_workflow_run):
    ctx = ToolContext(
        session=db_session,
        requesting_customer_id="someone_else",
        workflow_run_id=seeded_workflow_run["workflow_run_id"],
        tenant_id=DEFAULT_TENANT_ID,
    )

    with pytest.raises(AuthorizationError):
        await order_tools.get_order(
            ctx,
            order_tools.GetOrderArgs(
                customer_id=seeded_customer["customer_id"], order_id=seeded_customer["order_id"]
            ),
        )


@pytest.mark.asyncio
async def test_can_access_own_order(db_session, seeded_customer, seeded_workflow_run):
    ctx = ToolContext(
        session=db_session,
        requesting_customer_id=seeded_customer["customer_id"],
        workflow_run_id=seeded_workflow_run["workflow_run_id"],
        tenant_id=DEFAULT_TENANT_ID,
    )

    result = await order_tools.get_order(
        ctx,
        order_tools.GetOrderArgs(
            customer_id=seeded_customer["customer_id"], order_id=seeded_customer["order_id"]
        ),
    )
    assert result.order_id == seeded_customer["order_id"]


@pytest.mark.asyncio
async def test_unauthorized_tool_never_ai_allowed(db_session, seeded_customer, seeded_workflow_run):
    from pydantic import BaseModel

    from app.tools.base import run_tool

    class _Args(BaseModel):
        pass

    async def _noop():
        return None

    ctx = ToolContext(
        session=db_session,
        requesting_customer_id=seeded_customer["customer_id"],
        workflow_run_id=seeded_workflow_run["workflow_run_id"],
        tenant_id=DEFAULT_TENANT_ID,
    )
    with pytest.raises(AuthorizationError):
        await run_tool(
            ctx=ctx,
            tool_name="security_investigation",
            target_customer_id=seeded_customer["customer_id"],
            args=_Args(),
            fn=_noop,
        )
