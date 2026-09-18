from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.enums import Channel


class SupportMessageRequest(BaseModel):
    conversation_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=8000)
    channel: Channel = Channel.WEB
    metadata: dict = Field(default_factory=dict)


class SupportMessageResponse(BaseModel):
    conversation_id: str
    workflow_run_id: str
    status: str
    response: str | None
    requires_human: bool
    ticket_id: str | None = None
