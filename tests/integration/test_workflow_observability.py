"""Verifies app.workflow.graph._traced actually populates workflow_events
(spec §22/§27: every workflow decision must be observable) - it's easy for
this kind of cross-cutting logging to silently stop firing.
"""

import uuid

import pytest
from sqlalchemy import select

from app.domain.models import WorkflowEvent


@pytest.mark.asyncio
async def test_workflow_run_produces_node_events(client, auth_token, seeded_customer, db_session):
    response = await client.post(
        "/api/v1/support/messages",
        json={
            "conversation_id": f"conv_{uuid.uuid4().hex[:8]}",
            "message_id": f"msg_{uuid.uuid4().hex[:8]}",
            "message": "Where is my order?",
            "channel": "web",
        },
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200
    workflow_run_id = response.json()["workflow_run_id"]

    result = await db_session.execute(
        select(WorkflowEvent).where(WorkflowEvent.workflow_run_id == workflow_run_id)
    )
    events = result.scalars().all()

    node_names = {e.node_name for e in events}
    assert "validate_input" in node_names
    assert "resolve_issue" in node_names
    assert "save_outcome" in node_names
    assert all(e.status == "succeeded" for e in events)
    assert all(e.duration_ms is not None and e.duration_ms >= 0 for e in events)
