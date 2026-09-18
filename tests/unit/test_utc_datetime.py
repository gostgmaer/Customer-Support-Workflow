"""UTCDateTime (app.db.base): SQLite has no native timezone-aware datetime
type and silently hands back a *naive* datetime on read even though every
value written here is UTC. A naive datetime serializes with no timezone
suffix at all (e.g. "2026-09-09T08:23:47.788417"), which any consumer
doing `new Date(...)` on - the frontend included - parses as *local* time
instead of UTC, silently shifting every displayed timestamp. This is a
regression test for that fix, not the underlying feature.
"""

import pytest

from app.db.base import DEFAULT_TENANT_ID


@pytest.mark.asyncio
async def test_created_at_round_trips_as_utc_aware(db_session):
    from app.domain.models import Customer

    customer = Customer(email="tz-check@example.com", full_name="TZ Check", tenant_id=DEFAULT_TENANT_ID)
    db_session.add(customer)
    await db_session.commit()
    await db_session.refresh(customer)

    assert customer.created_at.tzinfo is not None
    assert customer.created_at.utcoffset().total_seconds() == 0


@pytest.mark.asyncio
async def test_api_serializes_created_at_with_a_utc_offset(client, admin_staff_token):
    response = await client.get(
        "/api/v1/staff/users", headers={"Authorization": f"Bearer {admin_staff_token}"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body, "expected at least the seeded admin"
    created_at = body[0]["created_at"]
    assert created_at.endswith("Z") or "+00:00" in created_at, (
        f"created_at {created_at!r} has no timezone suffix - a JS `new Date()` "
        "on this would be misread as local time"
    )
