"""app.realtime.connections.ConnectionManager (spec: Phase 10.3) - a
process-local websocket registry, exercised here with fake WebSocket-like
objects rather than a real ASGI connection (tests/integration/test_support_ws.py
covers the real route end to end)."""

from __future__ import annotations

from app.realtime.connections import ConnectionManager, get_connection_manager


class _FakeWebSocket:
    def __init__(self, *, fails: bool = False) -> None:
        self.fails = fails
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        if self.fails:
            raise RuntimeError("connection closed")
        self.sent.append(payload)


async def test_broadcast_delivers_to_all_registered_sockets_for_that_conversation():
    manager = ConnectionManager()
    ws1, ws2 = _FakeWebSocket(), _FakeWebSocket()
    await manager.register("conv_1", ws1)
    await manager.register("conv_1", ws2)

    await manager.broadcast("conv_1", {"event": "order.shipped"})

    assert ws1.sent == [{"event": "order.shipped"}]
    assert ws2.sent == [{"event": "order.shipped"}]


async def test_broadcast_does_not_reach_a_different_conversation():
    manager = ConnectionManager()
    ws1, ws2 = _FakeWebSocket(), _FakeWebSocket()
    await manager.register("conv_1", ws1)
    await manager.register("conv_2", ws2)

    await manager.broadcast("conv_1", {"event": "order.shipped"})

    assert ws1.sent == [{"event": "order.shipped"}]
    assert ws2.sent == []


async def test_unregister_stops_further_delivery():
    manager = ConnectionManager()
    ws = _FakeWebSocket()
    await manager.register("conv_1", ws)
    manager.unregister("conv_1", ws)

    await manager.broadcast("conv_1", {"event": "order.shipped"})

    assert ws.sent == []


async def test_a_dead_socket_is_dropped_without_breaking_delivery_to_others():
    manager = ConnectionManager()
    dead, alive = _FakeWebSocket(fails=True), _FakeWebSocket()
    await manager.register("conv_1", dead)
    await manager.register("conv_1", alive)

    await manager.broadcast("conv_1", {"event": "order.shipped"})

    assert alive.sent == [{"event": "order.shipped"}]
    # The dead socket must be unregistered so a second broadcast doesn't
    # keep failing silently on it forever.
    assert "conv_1" in manager._connections
    assert dead not in manager._connections["conv_1"]


def test_get_connection_manager_returns_a_singleton():
    assert get_connection_manager() is get_connection_manager()
