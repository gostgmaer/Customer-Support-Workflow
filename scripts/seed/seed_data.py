"""Seeds customers, orders, payments, subscriptions, and the knowledge base.

Run with:  python scripts/seed/seed_data.py
Prints a bearer JWT for each seeded customer so you can exercise the API
immediately (see README.md "Quick start").
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.db.session import get_sessionmaker, init_models  # noqa: E402
from app.domain.enums.role import StaffRole  # noqa: E402
from app.domain.models import Customer, Order, Payment, StaffUser, Subscription  # noqa: E402
from app.rag.ingest import ingest_knowledge_directory  # noqa: E402
from app.security.auth import create_access_token  # noqa: E402
from app.security.passwords import hash_password  # noqa: E402

DEV_STAFF_PASSWORD = "dev-agent-password"  # noqa: S105 - local/dev seed data only
DEV_CUSTOMER_PASSWORD = "dev-customer-password"  # noqa: S105 - local/dev seed data only

KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"


async def seed() -> None:
    await init_models()
    session_factory = get_sessionmaker()

    async with session_factory() as session:
        now = datetime.now(UTC)

        alice = Customer(
            id="cust_alice",
            email="alice@example.com",
            full_name="Alice Rivera",
            tier="standard",
            password_hash=hash_password(DEV_CUSTOMER_PASSWORD),
        )
        bob = Customer(
            id="cust_bob",
            email="bob@example.com",
            full_name="Bob Chen",
            tier="vip",
            password_hash=hash_password(DEV_CUSTOMER_PASSWORD),
        )
        session.add_all([alice, bob])
        await session.flush()

        order1 = Order(
            id="order_1001",
            customer_id=alice.id,
            status="in_transit",
            total_amount=89.99,
            currency="USD",
            product_name="Wireless Headphones",
            carrier="FastShip",
            tracking_number="FS123456789",
            estimated_delivery=now + timedelta(days=2),
            placed_at=now - timedelta(days=3),
        )
        order2 = Order(
            id="order_1002",
            customer_id=alice.id,
            status="delivered",
            total_amount=249.50,
            currency="USD",
            product_name="Mechanical Keyboard",
            carrier="FastShip",
            tracking_number="FS987654321",
            estimated_delivery=now - timedelta(days=10),
            placed_at=now - timedelta(days=20),
        )
        order3 = Order(
            id="order_2001",
            customer_id=bob.id,
            status="placed",
            total_amount=59.00,
            currency="USD",
            product_name="USB-C Hub",
            placed_at=now - timedelta(hours=2),
        )
        session.add_all([order1, order2, order3])
        await session.flush()

        session.add_all(
            [
                Payment(order_id=order1.id, customer_id=alice.id, status="succeeded", amount=89.99),
                Payment(order_id=order2.id, customer_id=alice.id, status="succeeded", amount=249.50),
                Payment(
                    order_id=order3.id,
                    customer_id=bob.id,
                    status="failed",
                    amount=59.00,
                    failure_reason="insufficient_funds",
                ),
            ]
        )

        session.add(
            Subscription(
                customer_id=bob.id, plan="Pro Annual", status="active", renews_at=now + timedelta(days=200)
            )
        )

        staff_accounts = [
            ("staff_jane", "agent_jane", StaffRole.SUPPORT_AGENT),
            ("staff_mo", "manager_mo", StaffRole.SUPPORT_MANAGER),
            ("staff_priya", "admin_priya", StaffRole.ADMIN),
            ("staff_sam", "security_sam", StaffRole.SECURITY_AGENT),
        ]
        session.add_all(
            [
                StaffUser(
                    id=staff_id,
                    username=username,
                    password_hash=hash_password(DEV_STAFF_PASSWORD),
                    role=role.value,
                )
                for staff_id, username, role in staff_accounts
            ]
        )

        await session.commit()

        chunk_count = await ingest_knowledge_directory(KNOWLEDGE_DIR, session)
        print(f"Ingested {chunk_count} knowledge chunks from {KNOWLEDGE_DIR}")

    print(
        f"\nSeeded customers (log in via POST /api/v1/customers/login, "
        f"all share password={DEV_CUSTOMER_PASSWORD}):"
    )
    for customer in (alice, bob):
        token = create_access_token(customer.id, expiry_minutes=24 * 60)
        print(f"  {customer.full_name} ({customer.email}): Bearer {token}")

    print(
        "\nSeeded staff users (log in via POST /api/v1/staff/login to get a bearer token, "
        f"all share password={DEV_STAFF_PASSWORD}):"
    )
    for _staff_id, username, role in staff_accounts:
        print(f"  {username} ({role.value})")


if __name__ == "__main__":
    asyncio.run(seed())
