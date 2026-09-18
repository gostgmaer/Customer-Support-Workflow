from __future__ import annotations

from pydantic import BaseModel


class KnowledgeCategorySummary(BaseModel):
    category: str
    article_count: int


class KnowledgeArticleSummary(BaseModel):
    id: str
    title: str
    category: str
    summary: str
    view_count: int
    helpful_percent: int | None
    updated_at: str


class KnowledgeArticleDetail(BaseModel):
    id: str
    title: str
    category: str
    source: str
    version: str
    raw_text: str
    view_count: int
    helpful_yes_count: int
    helpful_no_count: int
    helpful_percent: int | None
    created_at: str
    updated_at: str


class KnowledgeFeedbackRequest(BaseModel):
    helpful: bool


class KnowledgeAskRequest(BaseModel):
    question: str


class KnowledgeAskSource(BaseModel):
    id: str
    title: str
    category: str


class KnowledgeAskResponse(BaseModel):
    answer: str
    grounded: bool
    sources: list[KnowledgeAskSource]
