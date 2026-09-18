"""DB-backed per-tenant runtime settings (spec §32/§43):
`GET/PUT/DELETE /api/v1/admin/settings` let an ADMIN tune a small allow-list
of operational tunables without an env var change or redeploy - see
app.config.dynamic_settings.
"""

import uuid

import pytest

from app.config import get_settings
from app.config.dynamic_settings import OVERRIDABLE_SETTINGS, SEED_UPDATED_BY


@pytest.mark.asyncio
async def test_admin_sees_settings_seeded_at_first_boot(client, admin_staff_token):
    """The default tenant is auto-seeded from app.config.get_settings() the
    first time the app starts (app.main's lifespan / the _isolated_database
    test fixture mirroring it) - so every key shows up as an "override"
    written by "system" with the env-derived value, not "default", from the
    very first GET. See "DB-backed runtime settings" in docs/SECURITY.md."""
    response = await client.get(
        "/api/v1/admin/settings", headers={"Authorization": f"Bearer {admin_staff_token}"}
    )
    assert response.status_code == 200
    body = response.json()
    settings = get_settings()
    assert {item["key"] for item in body} == OVERRIDABLE_SETTINGS
    for item in body:
        assert item["source"] == "override"
        assert item["updated_by"] == SEED_UPDATED_BY
        assert item["value"] == getattr(settings, item["key"])


@pytest.mark.asyncio
async def test_non_admin_cannot_read_or_write_settings(client, staff_token):
    headers = {"Authorization": f"Bearer {staff_token}"}
    assert (await client.get("/api/v1/admin/settings", headers=headers)).status_code == 403
    assert (
        await client.put(
            "/api/v1/admin/settings/rate_limit_per_window", json={"value": 5}, headers=headers
        )
    ).status_code == 403
    assert (
        await client.delete("/api/v1/admin/settings/rate_limit_per_window", headers=headers)
    ).status_code == 403


@pytest.mark.asyncio
async def test_admin_can_set_and_clear_an_override(client, admin_staff_token, seeded_admin):
    headers = {"Authorization": f"Bearer {admin_staff_token}"}

    put_response = await client.put(
        "/api/v1/admin/settings/rate_limit_per_window", json={"value": 5}, headers=headers
    )
    assert put_response.status_code == 200
    put_body = put_response.json()
    assert put_body["key"] == "rate_limit_per_window"
    assert put_body["value"] == 5
    assert put_body["source"] == "override"
    assert put_body["updated_by"] == seeded_admin["staff_id"]

    list_response = await client.get("/api/v1/admin/settings", headers=headers)
    listed = {item["key"]: item for item in list_response.json()}
    assert listed["rate_limit_per_window"]["source"] == "override"
    assert listed["rate_limit_per_window"]["value"] == 5

    delete_response = await client.delete("/api/v1/admin/settings/rate_limit_per_window", headers=headers)
    assert delete_response.status_code == 204

    listed_after = {
        item["key"]: item for item in (await client.get("/api/v1/admin/settings", headers=headers)).json()
    }
    assert listed_after["rate_limit_per_window"]["source"] == "default"
    assert listed_after["rate_limit_per_window"]["value"] == 30  # settings.py's RATE_LIMIT_PER_WINDOW default


@pytest.mark.asyncio
async def test_unknown_key_is_rejected(client, admin_staff_token):
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    response = await client.put(
        "/api/v1/admin/settings/database_url", json={"value": "postgresql://evil"}, headers=headers
    )
    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_out_of_range_value_is_rejected(client, admin_staff_token):
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    response = await client.put(
        "/api/v1/admin/settings/confidence_intent", json={"value": 1.5}, headers=headers
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_override_is_tenant_scoped(client, admin_staff_token, seeded_admin):
    from app.security.auth import create_staff_token

    other_tenant_token = create_staff_token(seeded_admin["staff_id"], role="ADMIN", tenant_id="tenant_b")

    await client.put(
        "/api/v1/admin/settings/rate_limit_per_window",
        json={"value": 7},
        headers={"Authorization": f"Bearer {other_tenant_token}"},
    )

    default_tenant_listing = {
        item["key"]: item
        for item in (
            await client.get(
                "/api/v1/admin/settings", headers={"Authorization": f"Bearer {admin_staff_token}"}
            )
        ).json()
    }
    # The default tenant was auto-seeded at startup (see
    # test_admin_sees_settings_seeded_at_first_boot), so its own row still
    # shows "override"/system-seeded value - the assertion that matters
    # here is that it's unaffected by tenant_b's change, not "default".
    assert default_tenant_listing["rate_limit_per_window"]["value"] == 30
    assert default_tenant_listing["rate_limit_per_window"]["updated_by"] == "system"

    other_tenant_listing = {
        item["key"]: item
        for item in (
            await client.get(
                "/api/v1/admin/settings", headers={"Authorization": f"Bearer {other_tenant_token}"}
            )
        ).json()
    }
    assert other_tenant_listing["rate_limit_per_window"]["source"] == "override"
    assert other_tenant_listing["rate_limit_per_window"]["value"] == 7


@pytest.mark.asyncio
async def test_llm_budget_override_forces_escalation(client, admin_staff_token, auth_token, seeded_customer):
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    response = await client.put(
        "/api/v1/admin/settings/llm_budget_usd_per_run", json={"value": 0}, headers=headers
    )
    assert response.status_code == 200

    message_response = await client.post(
        "/api/v1/support/messages",
        json={
            "conversation_id": f"conv_{uuid.uuid4().hex[:8]}",
            "message_id": f"msg_{uuid.uuid4().hex[:8]}",
            "message": "Where is my order?",
            "channel": "web",
        },
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert message_response.status_code == 200
    body = message_response.json()
    # A $0 budget override is exceeded by the very first (zero-cost mock)
    # call's recorded row on the *next* LLM-calling node, forcing escalation
    # (spec §42) - same behavior as an env-var LLM_BUDGET_USD_PER_RUN=0,
    # but set through the DB-backed API without a restart.
    assert body["requires_human"] is True
    assert body["status"] == "escalated"
