import os
import uuid

import pytest


@pytest.mark.asyncio
async def test_messages_endpoint_enforces_rate_limit(client, auth_token, seeded_customer, db_session):
    os.environ["RATE_LIMIT_PER_WINDOW"] = "2"
    os.environ["RATE_LIMIT_WINDOW_SECONDS"] = "60"
    from app.config import get_settings
    from app.config.dynamic_settings import reset_effective_settings_cache
    from app.db.base import DEFAULT_TENANT_ID
    from app.repositories.system_settings import SystemSettingRepository

    get_settings.cache_clear()
    # The default tenant is auto-seeded at startup (see docs/SECURITY.md:
    # "DB-backed runtime settings"), which freezes these two keys at
    # whatever they were then - clear those rows so the env vars actually
    # take effect, same as they would for a tenant that never got seeded.
    repo = SystemSettingRepository(db_session, DEFAULT_TENANT_ID)
    await repo.delete("rate_limit_per_window")
    await repo.delete("rate_limit_window_seconds")
    await db_session.commit()
    reset_effective_settings_cache()
    try:
        conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
        headers = {"Authorization": f"Bearer {auth_token}"}

        for _ in range(2):
            response = await client.post(
                "/api/v1/support/messages",
                json={
                    "conversation_id": conversation_id,
                    "message_id": f"msg_{uuid.uuid4().hex[:8]}",
                    "message": "Where is my order?",
                    "channel": "web",
                },
                headers=headers,
            )
            assert response.status_code == 200

        third = await client.post(
            "/api/v1/support/messages",
            json={
                "conversation_id": conversation_id,
                "message_id": f"msg_{uuid.uuid4().hex[:8]}",
                "message": "Where is my order?",
                "channel": "web",
            },
            headers=headers,
        )
        assert third.status_code == 429
        assert third.json()["code"] == "RATE_LIMIT_ERROR"
    finally:
        os.environ.pop("RATE_LIMIT_PER_WINDOW", None)
        os.environ.pop("RATE_LIMIT_WINDOW_SECONDS", None)
        get_settings.cache_clear()
