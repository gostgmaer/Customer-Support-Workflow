from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.domain.enums import Channel


class CreateConversationRequest(BaseModel):
    channel: Channel = Channel.WEB


class ConversationResponse(BaseModel):
    id: str
    customer_id: str
    channel: str
    status: str
    intent: str | None
    priority: str | None
    created_at: datetime


class MessageResponse(BaseModel):
    role: str
    content: str
    created_at: datetime
