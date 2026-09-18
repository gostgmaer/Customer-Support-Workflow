import pytest

from app.services.idempotency import IdempotencyService, build_idempotency_key


def test_build_idempotency_key():
    assert build_idempotency_key("conv1", "refund", "req1") == "conv1:refund:req1"


@pytest.mark.asyncio
async def test_run_once_does_not_repeat_side_effect(db_session):
    service = IdempotencyService(db_session)
    key = build_idempotency_key("conv1", "refund", "req1")
    calls = {"count": 0}

    async def create_refund():
        calls["count"] += 1
        return {"refund_id": "r1", "amount": 50}

    first, replayed_first = await service.run_once(key, "refund", create_refund)
    second, replayed_second = await service.run_once(key, "refund", create_refund)

    assert calls["count"] == 1
    assert first == second == {"refund_id": "r1", "amount": 50}
    assert replayed_first is False
    assert replayed_second is True
