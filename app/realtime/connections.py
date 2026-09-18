"""In-process websocket connection registry (spec: Phase 10.3) - lets the
inbound storefront webhook push a best-effort live nudge into an *active*
customer conversation, closing the gap docs/ARCHITECTURE.md's "Inbound
storefront webhooks" section already named explicitly.

Like `InMemoryRateLimiter`/`InMemoryVectorStore`, this is a process-local
registry - correct for a single API instance, not for a fleet. A real
multi-instance deployment needs a pub/sub-backed variant (this codebase
already has Redis via `USE_REDIS`/`RedisRateLimiter`, a natural fit) -
not built in this pass; documented as a deliberate gap in
docs/DEPLOYMENT.md, matching how the checkpointer/rate-limiter/vector-store
each shipped single-instance-first.

The push is always a best-effort UX nudge alongside the durable
`SupportTicket` the webhook route already creates, never a replacement
for it - a customer not currently connected simply doesn't get the
nudge.
"""

from __future__ import annotations

from typing import Any

from fastapi import WebSocket

from app.observability.logging import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}

    async def register(self, conversation_id: str, websocket: WebSocket) -> None:
        self._connections.setdefault(conversation_id, set()).add(websocket)

    def unregister(self, conversation_id: str, websocket: WebSocket) -> None:
        sockets = self._connections.get(conversation_id)
        if sockets is None:
            return
        sockets.discard(websocket)
        if not sockets:
            del self._connections[conversation_id]

    async def broadcast(self, conversation_id: str, payload: dict[str, Any]) -> None:
        sockets = list(self._connections.get(conversation_id, ()))
        for websocket in sockets:
            try:
                await websocket.send_json(payload)
            except Exception:  # noqa: BLE001 - a dead/closed socket shouldn't break delivery to others
                logger.info("realtime_broadcast_dropped_dead_socket", conversation_id=conversation_id)
                self.unregister(conversation_id, websocket)


_manager: ConnectionManager | None = None


def get_connection_manager() -> ConnectionManager:
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager
