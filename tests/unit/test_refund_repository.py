"""app.repositories.orders.RefundRepository.get/update_status (spec:
Phase 9.4a) - the two methods added to fix a real bug: nothing anywhere
in this codebase ever flipped RefundRequest.status away from "pending"
after a refund ticket was approved or rejected.
"""

from __future__ import annotations

from app.db.base import DEFAULT_TENANT_ID
from app.domain.models import RefundRequest
from app.repositories.orders import RefundRepository


async def test_get_returns_the_refund_by_id(db_session, seeded_customer):
    repo = RefundRepository(db_session, DEFAULT_TENANT_ID)
    refund = await repo.create(
        RefundRequest(
            order_id=seeded_customer["order_id"],
            customer_id=seeded_customer["customer_id"],
            amount=42.0,
            status="pending",
            reason="test",
            idempotency_key="idem_1",
        )
    )
    await db_session.commit()

    found = await repo.get(refund.id)

    assert found is not None
    assert found.id == refund.id


async def test_get_returns_none_for_unknown_id(db_session):
    repo = RefundRepository(db_session, DEFAULT_TENANT_ID)

    assert await repo.get("does-not-exist") is None


async def test_update_status_persists(db_session, seeded_customer):
    repo = RefundRepository(db_session, DEFAULT_TENANT_ID)
    refund = await repo.create(
        RefundRequest(
            order_id=seeded_customer["order_id"],
            customer_id=seeded_customer["customer_id"],
            amount=42.0,
            status="pending",
            reason="test",
            idempotency_key="idem_2",
        )
    )
    await db_session.commit()

    await repo.update_status(refund, "approved")
    await db_session.commit()

    reloaded = await repo.get(refund.id)
    assert reloaded is not None
    assert reloaded.status == "approved"
