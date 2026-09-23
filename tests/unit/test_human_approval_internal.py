"""app.workflow.nodes.human_approval._execute_approved_internal_call (spec:
Phase 13) - the internal-tool analogue of _execute_approved_external_call:
update_customer_profile/unlock_account only ever run here, after approval,
never during resolve_issue. Tested directly against a real DB session,
mirroring test_human_approval_external.py's pattern (bypassing
human_approval_gate's `interrupt()`, which only works inside a compiled
LangGraph run).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.base import DEFAULT_TENANT_ID
from app.domain.models import Customer
from app.workflow.deps import WorkflowDeps
from app.workflow.nodes.human_approval import _execute_approved_internal_call

pytestmark = pytest.mark.asyncio


def _fake_config(db_session) -> dict:
    deps = WorkflowDeps(session=db_session, llm_router=None, retriever=None)  # type: ignore[arg-type]
    return {"configurable": {"deps": deps}}


@pytest.fixture
async def state(seeded_customer, seeded_workflow_run) -> dict:
    return {
        "tenant_id": DEFAULT_TENANT_ID,
        "customer_id": seeded_customer["customer_id"],
        "workflow_run_id": seeded_workflow_run["workflow_run_id"],
        "resolution_facts": ["existing fact"],
    }


async def test_executes_update_customer_profile_and_persists_the_change(
    db_session, seeded_customer, state
):
    pending = {
        "tool": "update_customer_profile",
        "args": {"customer_id": seeded_customer["customer_id"], "new_email": "changed@example.com"},
    }

    result = await _execute_approved_internal_call(state, _fake_config(db_session), pending)

    assert "requires_human" not in result
    assert "existing fact" in result["resolution_facts"]
    assert result["execution_result"]["email"] == "changed@example.com"
    row = await db_session.execute(select(Customer).where(Customer.id == seeded_customer["customer_id"]))
    assert row.scalar_one().email == "changed@example.com"


async def test_executes_unlock_account_and_persists_the_change(db_session, seeded_customer, state):
    row = await db_session.execute(select(Customer).where(Customer.id == seeded_customer["customer_id"]))
    customer = row.scalar_one()
    customer.is_locked = True
    await db_session.commit()

    pending = {"tool": "unlock_account", "args": {"customer_id": seeded_customer["customer_id"]}}
    result = await _execute_approved_internal_call(state, _fake_config(db_session), pending)

    assert result["execution_result"]["unlocked"] is True
    row = await db_session.execute(select(Customer).where(Customer.id == seeded_customer["customer_id"]))
    assert row.scalar_one().is_locked is False


async def test_email_already_in_use_fails_and_escalates_without_applying(
    db_session, seeded_customer, state
):
    other = Customer(id="cust_other_1", email="taken@example.com", full_name="Other Customer")
    db_session.add(other)
    await db_session.commit()

    pending = {
        "tool": "update_customer_profile",
        "args": {"customer_id": seeded_customer["customer_id"], "new_email": "taken@example.com"},
    }
    result = await _execute_approved_internal_call(state, _fake_config(db_session), pending)

    assert result["requires_human"] is True
    assert "execution_result" in result and "error" in result["execution_result"]
    row = await db_session.execute(select(Customer).where(Customer.id == seeded_customer["customer_id"]))
    assert row.scalar_one().email != "taken@example.com"


async def test_unknown_pending_tool_escalates_without_crashing(db_session, state):
    pending = {"tool": "delete_everything", "args": {}}

    result = await _execute_approved_internal_call(state, _fake_config(db_session), pending)

    assert result["requires_human"] is True
    assert "unknown pending internal action" in result["escalation_reason"].lower()
