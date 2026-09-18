from __future__ import annotations

from sqlalchemy import select

from app.domain.models import Conversation, Message
from app.repositories.base import TenantScopedRepository


class ConversationRepository(TenantScopedRepository):
    async def get(self, conversation_id: str) -> Conversation | None:
        stmt = self._scope(select(Conversation).where(Conversation.id == conversation_id), Conversation)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(
        self, conversation_id: str, *, customer_id: str, channel: str
    ) -> Conversation:
        existing = await self.get(conversation_id)
        if existing is not None:
            return existing
        conversation = Conversation(
            id=conversation_id,
            tenant_id=self.tenant_id,
            customer_id=customer_id,
            channel=channel,
            status="open",
        )
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def update_status(self, conversation: Conversation, status: str) -> Conversation:
        conversation.status = status
        await self.session.flush()
        return conversation

    async def set_classification(
        self, conversation: Conversation, *, intent: str | None, priority: str | None
    ) -> Conversation:
        conversation.intent = intent
        conversation.priority = priority
        await self.session.flush()
        return conversation

    async def add_message(
        self, *, conversation_id: str, role: str, content: str, metadata: dict | None = None
    ) -> Message:
        message = Message(
            tenant_id=self.tenant_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            metadata_json=metadata or {},
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def history(self, conversation_id: str, *, limit: int = 50) -> list[Message]:
        stmt = self._scope(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc()),
            Message,
        ).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
