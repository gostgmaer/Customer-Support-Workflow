from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio


@pytest.fixture(scope="session", autouse=True)
def _test_environment():
    os.environ["APP_ENV"] = "test"
    os.environ["MOCK_LLM"] = "true"
    os.environ["VECTOR_BACKEND"] = "memory"
    os.environ["JWT_SECRET"] = "test-secret"
    # Settings.model_config reads .env directly (env_file=".env") - a real
    # provider key placed there for live/Docker testing must never leak
    # into a local test run and silently change behavior (e.g.
    # test_factory_raises_clear_error_for_unconfigured_provider assumes
    # get_provider("google") fails without a key). Explicit env vars take
    # precedence over .env in pydantic-settings, so blanking these here
    # keeps tests deterministic regardless of what's in .env.
    os.environ["GOOGLE_API_KEY"] = ""
    os.environ["XAI_API_KEY"] = ""
    os.environ["ANTHROPIC_API_KEY"] = ""
    from app.config import get_settings

    get_settings.cache_clear()
    yield


@pytest.fixture(autouse=True)
def _reset_in_memory_vector_store():
    from app.repositories.vector_store import InMemoryVectorStore

    InMemoryVectorStore.reset()
    yield
    InMemoryVectorStore.reset()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.security.rate_limit import InMemoryRateLimiter

    InMemoryRateLimiter.reset()
    yield
    InMemoryRateLimiter.reset()


@pytest.fixture(autouse=True)
def _reset_llm_router_state():
    from app.llm.factory import reset_provider_cache
    from app.llm.health import get_health_registry

    reset_provider_cache()
    get_health_registry().reset()
    yield
    reset_provider_cache()
    get_health_registry().reset()


@pytest_asyncio.fixture(autouse=True)
async def _isolated_database(tmp_path):
    """Gives every test its own sqlite file + checkpoint db and resets the
    process-wide engine/settings caches, so tests never see another test's
    rows (id collisions, ingestion-idempotency skips, etc.)."""
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    os.environ["CHECKPOINT_DB_PATH"] = str(tmp_path / "checkpoints.db")

    from app.config import get_settings
    from app.config.dynamic_settings import reset_effective_settings_cache

    get_settings.cache_clear()
    reset_effective_settings_cache()

    import app.db.session as db_session_module

    db_session_module._engine = None
    db_session_module._sessionmaker = None

    await db_session_module.init_models()

    from app.config.dynamic_settings import seed_default_settings
    from app.db.base import DEFAULT_TENANT_ID

    async with db_session_module.get_sessionmaker()() as session:
        await seed_default_settings(session, DEFAULT_TENANT_ID)

    yield

    engine = db_session_module._engine
    if engine is not None:
        await engine.dispose()
    db_session_module._engine = None
    db_session_module._sessionmaker = None


@pytest_asyncio.fixture
async def db_session():
    from app.db.session import get_sessionmaker, init_models

    await init_models()
    async with get_sessionmaker()() as session:
        yield session


CUSTOMER_TEST_PASSWORD = "correct-horse-battery-staple"  # noqa: S105 - test fixture only


@pytest_asyncio.fixture
async def seeded_customer(db_session):
    from app.domain.models import Customer, Order, Payment, Subscription
    from app.security.passwords import hash_password

    now = datetime.now(UTC)
    customer_id = f"cust_{uuid.uuid4().hex[:8]}"
    customer = Customer(
        id=customer_id,
        email=f"{customer_id}@example.com",
        full_name="Test Customer",
        password_hash=hash_password(CUSTOMER_TEST_PASSWORD),
    )
    db_session.add(customer)
    # Order.customer_id is a bare ForeignKey column, not an ORM
    # relationship() - flushing the parent before adding the child avoids
    # depending on SQLAlchemy's unit-of-work to infer an ordering it has no
    # relationship metadata to infer from (see app.rag.ingest's near-identical
    # fix - same underlying class of bug, caught here by enabling SQLite
    # FK enforcement in app.db.session).
    await db_session.flush()
    order = Order(
        id=f"order_{uuid.uuid4().hex[:8]}",
        customer_id=customer_id,
        status="in_transit",
        total_amount=99.99,
        currency="USD",
        product_name="Test Product",
        carrier="TestCarrier",
        tracking_number="TC123",
        estimated_delivery=now + timedelta(days=2),
        placed_at=now - timedelta(days=1),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(Payment(order_id=order.id, customer_id=customer_id, status="succeeded", amount=99.99))
    db_session.add(Subscription(customer_id=customer_id, plan="Pro", status="active"))
    await db_session.commit()
    return {
        "customer_id": customer_id,
        "order_id": order.id,
        "email": customer.email,
        "password": CUSTOMER_TEST_PASSWORD,
    }


@pytest_asyncio.fixture
async def seeded_workflow_run(db_session, seeded_customer):
    """A real Conversation + WorkflowRun row, for tests that need a valid
    `workflow_run_id`/`conversation_id` to reference (both are bare
    ForeignKey columns - see app.workflow.runner's fix - so a fabricated
    id like "wf1" now fails the same FK check a real deployment enforces)."""
    from app.db.base import DEFAULT_TENANT_ID
    from app.domain.models import Conversation, WorkflowRun

    conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
    db_session.add(
        Conversation(
            id=conversation_id,
            tenant_id=DEFAULT_TENANT_ID,
            customer_id=seeded_customer["customer_id"],
            channel="web",
            status="open",
        )
    )
    await db_session.flush()
    run = WorkflowRun(
        tenant_id=DEFAULT_TENANT_ID,
        conversation_id=conversation_id,
        message_id=f"msg_{uuid.uuid4().hex[:8]}",
        status="running",
    )
    db_session.add(run)
    await db_session.flush()
    await db_session.commit()
    return {"conversation_id": conversation_id, "workflow_run_id": run.id}


@pytest.fixture
def auth_token(seeded_customer):
    from app.security.auth import create_access_token

    return create_access_token(seeded_customer["customer_id"])


async def _make_staff(db_session, role: str):
    from app.domain.models import StaffUser
    from app.security.passwords import hash_password

    staff_id = f"staff_{uuid.uuid4().hex[:8]}"
    staff = StaffUser(
        id=staff_id,
        username=f"staff_{uuid.uuid4().hex[:6]}",
        password_hash=hash_password("correct-horse-battery-staple"),
        role=role,
        is_active=True,
    )
    db_session.add(staff)
    await db_session.commit()
    return {"staff_id": staff_id, "username": staff.username, "password": "correct-horse-battery-staple"}


@pytest_asyncio.fixture
async def seeded_staff(db_session):
    return await _make_staff(db_session, "SUPPORT_AGENT")


@pytest_asyncio.fixture
async def seeded_security_agent(db_session):
    return await _make_staff(db_session, "SECURITY_AGENT")


@pytest_asyncio.fixture
async def seeded_admin(db_session):
    return await _make_staff(db_session, "ADMIN")


@pytest.fixture
def staff_token(seeded_staff):
    from app.security.auth import create_staff_token

    return create_staff_token(seeded_staff["staff_id"], role="SUPPORT_AGENT")


@pytest.fixture
def security_staff_token(seeded_security_agent):
    from app.security.auth import create_staff_token

    return create_staff_token(seeded_security_agent["staff_id"], role="SECURITY_AGENT")


@pytest.fixture
def admin_staff_token(seeded_admin):
    from app.security.auth import create_staff_token

    return create_staff_token(seeded_admin["staff_id"], role="ADMIN")


@pytest_asyncio.fixture
async def client():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
