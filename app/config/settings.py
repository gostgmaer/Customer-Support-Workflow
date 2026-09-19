"""Central application configuration (spec §32: no hard-coded thresholds).

All environment variables are declared here with sane zero-setup defaults
(sqlite + in-memory vector store + mock LLM) so `make dev` works with no
external services. Production overrides these via environment variables /
.env (see .env.example).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # --- App ---
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    # Comma-separated origins the browser-based frontend is served from
    # (e.g. "http://localhost:3000,https://support.example.com"). The
    # zero-setup default covers `pnpm dev`'s default port.
    cors_allowed_origins_raw: str = Field(
        default="http://localhost:3000", alias="CORS_ALLOWED_ORIGINS"
    )

    # --- Database ---
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/support.db", alias="DATABASE_URL"
    )
    checkpoint_db_path: str = Field(default="./data/checkpoints.db", alias="CHECKPOINT_DB_PATH")
    # spec: Phase 9.1a - sqlite (default, zero-setup, single-instance only)
    # or postgres (required once more than one API instance handles
    # human-approval interrupts - see app.workflow.runner.get_checkpointer
    # and docs/DEPLOYMENT.md). Mirrors VECTOR_BACKEND's own
    # env-var-selected-backend pattern below.
    checkpoint_backend: str = Field(default="sqlite", alias="CHECKPOINT_BACKEND")  # sqlite | postgres

    # --- Vector store ---
    vector_backend: str = Field(default="memory", alias="VECTOR_BACKEND")  # memory | pgvector
    vector_dimensions: int = Field(default=384, alias="VECTOR_DIMENSIONS")

    # --- LLM (spec §3-5, §44, §48) ---
    # The entire system must be runnable without paid LLM APIs (spec §48).
    # Defaults to true; production sets MOCK_LLM=false + real provider keys.
    mock_llm: bool = Field(default=True, alias="MOCK_LLM")

    default_llm_provider: str = Field(default="google", alias="DEFAULT_LLM_PROVIDER")
    fallback_llm_provider: str = Field(default="xai", alias="FALLBACK_LLM_PROVIDER")

    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    google_model: str = Field(default="gemini-3.1-flash-lite", alias="GOOGLE_MODEL")

    xai_api_key: str = Field(default="", alias="XAI_API_KEY")
    xai_model: str = Field(default="grok-4-fast", alias="XAI_MODEL")

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-5", alias="ANTHROPIC_MODEL")

    # --- LangSmith (spec §13-15) ---
    langsmith_api_key: str = Field(default="", alias="LANGSMITH_API_KEY")
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")
    langsmith_project: str = Field(default="customer-support-workflow", alias="LANGSMITH_PROJECT")

    # --- Cost tracking / budget (spec §42) ---
    # None = unlimited (zero-setup default). Set to enforce a per-workflow-run
    # USD ceiling on LLM spend - once hit, remaining LLM-calling nodes in
    # that run are skipped and the run escalates to a human instead.
    llm_budget_usd_per_run: float | None = Field(default=None, alias="LLM_BUDGET_USD_PER_RUN")

    @field_validator("llm_budget_usd_per_run", mode="before")
    @classmethod
    def _blank_budget_means_unset(cls, value: object) -> object:
        # An empty .env value (`LLM_BUDGET_USD_PER_RUN=`, the documented
        # "unlimited" way to leave it, per .env.example) must mean None -
        # pydantic doesn't coerce "" to None for a float field on its own.
        return None if value == "" else value

    # --- Auth ---
    jwt_secret: str = Field(default="change-me-in-production", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expiry_minutes: int = Field(default=60, alias="JWT_EXPIRY_MINUTES")
    # spec: Phase 9.1c - dedicated key for encrypting Integration.encrypted_credentials
    # (app.integrations.crypto). Blank (the zero-setup default) falls back
    # to deriving the key from jwt_secret, today's only behavior - set
    # this in production so rotating JWT_SECRET doesn't also break every
    # stored integration credential. See docs/SECURITY.md.
    credentials_encryption_key: str = Field(default="", alias="CREDENTIALS_ENCRYPTION_KEY")

    # --- Redis ---
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    use_redis: bool = Field(default=False, alias="USE_REDIS")

    # --- Confidence thresholds ---
    confidence_intent: float = Field(default=0.80, alias="CONFIDENCE_INTENT")
    # Calibrated for the default HashingEmbedder + lexical-weighted reranker
    # (see app.rag.reranker) - its combined scores run much lower than a
    # real semantic embedding model's. Raise this if RAG_EMBEDDER is swapped
    # for a real embeddings API/model.
    confidence_retrieval: float = Field(default=0.30, alias="CONFIDENCE_RETRIEVAL")
    confidence_response: float = Field(default=0.85, alias="CONFIDENCE_RESPONSE")

    # --- Retry ---
    retry_max_attempts: int = Field(default=3, alias="RETRY_MAX_ATTEMPTS")

    # --- Escalation ---
    escalation_max_failed_attempts: int = Field(
        default=2, alias="ESCALATION_MAX_FAILED_ATTEMPTS"
    )

    # --- Security ---
    security_require_human_approval: bool = Field(
        default=True, alias="SECURITY_REQUIRE_HUMAN_APPROVAL"
    )

    # --- Rate limiting (spec §23) ---
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    rate_limit_per_window: int = Field(default=30, alias="RATE_LIMIT_PER_WINDOW")
    rate_limit_window_seconds: int = Field(default=60, alias="RATE_LIMIT_WINDOW_SECONDS")

    # --- OAuth2 (Google Drive / SharePoint docs connectors, spec: Phase 10.4) ---
    # Blank by default (zero-setup) - only needed for the two connectors
    # that use OAuth2 instead of a static token (Confluence/Notion, Phase
    # 9.3, need none of this). Register an app in Google Cloud Console /
    # Azure AD to get these - see docs/DEPLOYMENT.md.
    google_oauth_client_id: str = Field(default="", alias="GOOGLE_OAUTH_CLIENT_ID")
    google_oauth_client_secret: str = Field(default="", alias="GOOGLE_OAUTH_CLIENT_SECRET")
    google_oauth_redirect_uri: str = Field(default="", alias="GOOGLE_OAUTH_REDIRECT_URI")

    microsoft_oauth_client_id: str = Field(default="", alias="MICROSOFT_OAUTH_CLIENT_ID")
    microsoft_oauth_client_secret: str = Field(default="", alias="MICROSOFT_OAUTH_CLIENT_SECRET")
    microsoft_oauth_tenant_id: str = Field(default="common", alias="MICROSOFT_OAUTH_TENANT_ID")
    microsoft_oauth_redirect_uri: str = Field(default="", alias="MICROSOFT_OAUTH_REDIRECT_URI")

    # --- Original-file storage (spec: KB upload keeps the source file, not
    # just its extracted text) - one provider active at a time, chosen by
    # FILE_STORAGE_PROVIDER, mirroring VECTOR_BACKEND/CHECKPOINT_BACKEND's
    # own pluggable-backend pattern above. Cloudflare R2 is the default
    # (S3-compatible, no egress fees); "local" (zero-setup, writes under
    # ./data/uploads) is what tests and an unconfigured dev checkout
    # actually get, since none of the cloud providers have real
    # zero-config credentials. Switching providers later doesn't move
    # already-stored files by itself - see scripts/storage/migrate_file_storage.py.
    file_storage_provider: str = Field(default="r2", alias="FILE_STORAGE_PROVIDER")  # r2 | s3 | azure | local
    local_storage_dir: str = Field(default="./data/uploads", alias="LOCAL_STORAGE_DIR")

    # R2 (Cloudflare) - S3-compatible; endpoint is account-specific, unlike
    # real AWS S3's fixed regional endpoints.
    r2_account_id: str = Field(default="", alias="R2_ACCOUNT_ID")
    r2_access_key_id: str = Field(default="", alias="R2_ACCESS_KEY_ID")
    r2_secret_access_key: str = Field(default="", alias="R2_SECRET_ACCESS_KEY")
    r2_bucket: str = Field(default="", alias="R2_BUCKET")

    # AWS S3
    s3_access_key_id: str = Field(default="", alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str = Field(default="", alias="S3_SECRET_ACCESS_KEY")
    s3_bucket: str = Field(default="", alias="S3_BUCKET")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")

    # Azure Blob Storage
    azure_storage_connection_string: str = Field(default="", alias="AZURE_STORAGE_CONNECTION_STRING")
    azure_storage_container: str = Field(default="", alias="AZURE_STORAGE_CONTAINER")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def cors_allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins_raw.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    Path("./data").mkdir(parents=True, exist_ok=True)
    return Settings()
