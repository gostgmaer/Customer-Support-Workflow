"""Cost tracking (spec §42): a model_requests row per LLM call, and budget
enforcement forcing escalation once a run's spend is exceeded.
"""

import os
import uuid

import pytest
from sqlalchemy import select

from app.db.base import DEFAULT_TENANT_ID
from app.domain.models import ModelRequest


@pytest.mark.asyncio
async def test_model_requests_recorded_for_a_workflow_run(client, auth_token, seeded_customer, db_session):
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
        select(ModelRequest).where(ModelRequest.workflow_run_id == workflow_run_id)
    )
    rows = result.scalars().all()

    # classify_intent, classify_priority, detect_sentiment, resolve_issue,
    # policy_check, grounding_check, response_review all call the mock LLM.
    assert len(rows) >= 5
    assert all(r.provider == "mock" for r in rows)
    assert all(r.tenant_id == DEFAULT_TENANT_ID for r in rows)
    assert {r.node_name for r in rows} >= {"classify_intent", "resolve_issue", "policy_check"}


@pytest.mark.asyncio
async def test_budget_exceeded_forces_escalation(client, auth_token, seeded_customer, db_session):
    os.environ["LLM_BUDGET_USD_PER_RUN"] = "0"
    from app.config import get_settings
    from app.config.dynamic_settings import reset_effective_settings_cache
    from app.repositories.system_settings import SystemSettingRepository

    get_settings.cache_clear()
    # The default tenant is auto-seeded at startup (see docs/SECURITY.md:
    # "DB-backed runtime settings"), which freezes llm_budget_usd_per_run
    # at whatever it was then - clear that row so this env var actually
    # takes effect, same as it would for a tenant that never got seeded.
    await SystemSettingRepository(db_session, DEFAULT_TENANT_ID).delete("llm_budget_usd_per_run")
    await db_session.commit()
    reset_effective_settings_cache()
    try:
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
        body = response.json()
        # A $0 budget is exceeded by the very first (zero-cost mock) call's
        # recorded row on the *next* LLM-calling node, forcing escalation
        # rather than a silently-produced answer (spec §42).
        assert body["requires_human"] is True
        assert body["status"] == "escalated"
    finally:
        os.environ.pop("LLM_BUDGET_USD_PER_RUN", None)
        get_settings.cache_clear()
