"""Per-invocation dependencies threaded through LangGraph node `config`
(never through state, since state must stay checkpoint-serializable).
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.runnables import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.router import LLMRouterLike
from app.rag.retriever import Retriever


@dataclass
class WorkflowDeps:
    session: AsyncSession
    llm_router: LLMRouterLike
    retriever: Retriever


def get_deps(config: RunnableConfig) -> WorkflowDeps:
    return config["configurable"]["deps"]
