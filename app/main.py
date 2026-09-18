"""FastAPI application entrypoint (spec §26)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.routes import (
    admin_settings,
    customers,
    health,
    integrations,
    knowledge,
    oauth_callback,
    staff,
    support,
    tickets,
    webhooks,
)
from app.config import get_settings
from app.config.dynamic_settings import seed_default_settings
from app.db.base import DEFAULT_TENANT_ID
from app.db.session import get_sessionmaker, init_models
from app.domain.exceptions import SupportWorkflowError
from app.observability.logging import clear_context, configure_logging, get_logger
from app.observability.tracing import configure_langsmith
from app.rag.ingest import warm_vector_index_from_db

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_langsmith(settings)
    if settings.is_sqlite:
        await init_models()
    async with get_sessionmaker()() as session:
        seeded = await seed_default_settings(session, DEFAULT_TENANT_ID)
        logger.info("system_settings_seed", seeded=seeded, tenant_id=DEFAULT_TENANT_ID)
    if settings.vector_backend == "memory":
        async with get_sessionmaker()() as session:
            count = await warm_vector_index_from_db(session)
            logger.info("vector_index_warmed", chunk_count=count)
    logger.info(
        "app_startup",
        app_env=settings.app_env,
        mock_llm=settings.mock_llm,
        default_llm_provider=settings.default_llm_provider,
        fallback_llm_provider=settings.fallback_llm_provider,
    )
    yield
    logger.info("app_shutdown")


app = FastAPI(
    title="Customer Support Workflow",
    description="Production-grade AI customer support workflow (FastAPI + LangGraph + LangChain)",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def clear_logging_context_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    finally:
        clear_context()


@app.exception_handler(SupportWorkflowError)
async def support_error_handler(request: Request, exc: SupportWorkflowError) -> JSONResponse:
    status_map = {
        "VALIDATION_ERROR": 400,
        "AUTHENTICATION_ERROR": 401,
        "AUTHORIZATION_ERROR": 403,
        "RATE_LIMIT_ERROR": 429,
    }
    status_code = status_map.get(exc.code, 500 if exc.severity == "high" else 422)
    logger.error("request_failed", code=exc.code, message=exc.message, path=str(request.url))
    return JSONResponse(status_code=status_code, content=exc.to_dict())


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


app.include_router(health.router, prefix="/api/v1")
app.include_router(customers.router)
app.include_router(staff.router)
app.include_router(support.router)
app.include_router(tickets.router)
app.include_router(admin_settings.router)
app.include_router(integrations.admin_router)
app.include_router(integrations.support_router)
app.include_router(webhooks.router)
app.include_router(oauth_callback.router)
app.include_router(knowledge.router)
