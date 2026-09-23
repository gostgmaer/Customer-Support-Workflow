from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SubmitFeedbackRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = ""


class FeedbackResponse(BaseModel):
    id: str
    conversation_id: str
    rating: int
    comment: str
    resolved: bool
    created_at: datetime
