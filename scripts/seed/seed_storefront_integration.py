"""Connects the committed demo storefront (spec: Phase 8.1) as a real
`openapi` Integration tagged as this tenant's primary storefront, so a
fresh environment has storefront-primary commerce routing
(app.agents.resolution.resolve_via_storefront) working out of the box
instead of requiring a manual admin-API call every time.

Run with:  python scripts/seed/seed_storefront_integration.py
Assumes demo_storefront is reachable at STOREFRONT_BASE_URL (defaults to
the docker-compose service DNS name; override for local/non-Docker runs,
e.g. STOREFRONT_BASE_URL=http://localhost:8100).
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.db.base import DEFAULT_TENANT_ID  # noqa: E402
from app.db.session import get_sessionmaker, init_models  # noqa: E402
from app.domain.models import Integration  # noqa: E402
from app.integrations.base import encode_credentials  # noqa: E402
from app.repositories.integrations import IntegrationRepository  # noqa: E402

STOREFRONT_BASE_URL = os.environ.get("STOREFRONT_BASE_URL", "http://demo_storefront:8000")


async def seed() -> None:
    await init_models()
    session_factory = get_sessionmaker()

    async with session_factory() as session:
        repo = IntegrationRepository(session, DEFAULT_TENANT_ID)
        integration = Integration(
            id=f"int_{uuid.uuid4().hex[:8]}",
            tenant_id=DEFAULT_TENANT_ID,
            name="Demo Storefront",
            type="openapi",
            base_url=STOREFRONT_BASE_URL,
            auth_type="none",
            encrypted_credentials=encode_credentials({}),
            config={
                "spec_url": f"{STOREFRONT_BASE_URL}/openapi.json",
                "role": "storefront",
                "auto_execute_reads": True,
            },
            enabled=True,
            created_by="staff_admin",
        )
        await repo.create(integration)
        await session.commit()
        print(f"Connected demo storefront integration {integration.id} at {STOREFRONT_BASE_URL}")
        print('Click "Test" on it in /admin/integrations (or POST .../test) to cache its operations.')


if __name__ == "__main__":
    asyncio.run(seed())
