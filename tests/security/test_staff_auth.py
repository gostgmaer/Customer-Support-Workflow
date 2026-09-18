"""Staff RBAC (spec §18/§26/§36 approve/reject is a separate trust boundary
from the customer API - see docs/SECURITY.md). Covers the real login flow,
the scope separation between customer/staff/system tokens, and the
security-queue role restriction.
"""

import uuid

import pytest

from app.db.base import DEFAULT_TENANT_ID
from app.domain.exceptions import AuthenticationError
from app.security.auth import create_access_token, decode_staff_token


async def _make_conversation(db_session, suffix: str) -> tuple[str, str]:
    """A real Customer + Conversation, for tests that need a valid
    `customer_id`/`conversation_id` to reference on a directly-constructed
    SupportTicket - both are bare ForeignKey columns (see
    app.workflow.runner's fix), so a fabricated id like "cust_sec" now
    fails the same FK check a real deployment enforces."""
    from app.domain.models import Conversation, Customer

    customer_id = f"cust_{suffix}_{uuid.uuid4().hex[:6]}"
    db_session.add(
        Customer(id=customer_id, email=f"{customer_id}@example.com", full_name="Test Customer")
    )
    await db_session.flush()
    conversation_id = f"conv_{suffix}_{uuid.uuid4().hex[:6]}"
    db_session.add(
        Conversation(
            id=conversation_id,
            tenant_id=DEFAULT_TENANT_ID,
            customer_id=customer_id,
            channel="web",
            status="open",
        )
    )
    await db_session.flush()
    return customer_id, conversation_id


@pytest.mark.asyncio
async def test_staff_login_succeeds_with_correct_credentials(client, seeded_staff):
    response = await client.post(
        "/api/v1/staff/login",
        json={"username": seeded_staff["username"], "password": seeded_staff["password"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "SUPPORT_AGENT"
    assert body["access_token"]

    staff_id, role, tenant_id = decode_staff_token(body["access_token"])
    assert staff_id == seeded_staff["staff_id"]
    assert role == "SUPPORT_AGENT"
    assert tenant_id == DEFAULT_TENANT_ID


@pytest.mark.asyncio
async def test_staff_login_fails_with_wrong_password(client, seeded_staff):
    response = await client.post(
        "/api/v1/staff/login",
        json={"username": seeded_staff["username"], "password": "wrong-password"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_staff_login_fails_for_unknown_user(client):
    response = await client.post(
        "/api/v1/staff/login", json={"username": "nobody", "password": "whatever"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_customer_token_cannot_access_staff_endpoint(client, auth_token, seeded_customer):
    response = await client.get(
        "/api/v1/support/tickets/does-not-matter", headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 401


def test_staff_token_rejected_by_customer_decoder():
    from app.security.auth import create_staff_token, decode_access_token

    token = create_staff_token("staff_1", role="SUPPORT_AGENT")
    with pytest.raises(AuthenticationError):
        decode_access_token(token)


def test_customer_token_rejected_by_staff_decoder():
    token = create_access_token("cust_1")
    with pytest.raises(AuthenticationError):
        decode_staff_token(token)


def test_system_token_round_trips_and_is_a_distinct_scope():
    from app.security.auth import create_system_token, decode_staff_token, decode_system_token

    token = create_system_token("seed-script")
    system_id, tenant_id = decode_system_token(token)
    assert system_id == "seed-script"
    assert tenant_id == DEFAULT_TENANT_ID
    with pytest.raises(AuthenticationError):
        decode_staff_token(token)


@pytest.mark.asyncio
async def test_regular_agent_cannot_approve_security_ticket(client, staff_token, db_session):
    """spec §36/§52: SECURITY/FRAUD/LEGAL tickets are a restricted queue -
    only SECURITY_AGENT/ADMIN may act on them."""
    from app.domain.models import SupportTicket
    from app.repositories.tickets import TicketRepository

    customer_id, conversation_id = await _make_conversation(db_session, "sec")
    ticket = await TicketRepository(db_session, DEFAULT_TENANT_ID).create(
        SupportTicket(
            conversation_id=conversation_id,
            customer_id=customer_id,
            intent="SECURITY",
            priority="CRITICAL",
            status="open",
            summary="Suspicious login",
            customer_problem="I think someone accessed my account",
            reason_for_escalation="Security-sensitive request",
        )
    )
    await db_session.commit()

    response = await client.get(
        f"/api/v1/support/tickets/{ticket.id}", headers={"Authorization": f"Bearer {staff_token}"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_security_agent_can_view_security_ticket(client, security_staff_token, db_session):
    from app.domain.models import SupportTicket
    from app.repositories.tickets import TicketRepository

    customer_id, conversation_id = await _make_conversation(db_session, "sec2")
    ticket = await TicketRepository(db_session, DEFAULT_TENANT_ID).create(
        SupportTicket(
            conversation_id=conversation_id,
            customer_id=customer_id,
            intent="SECURITY",
            priority="CRITICAL",
            status="open",
            summary="Suspicious login",
            customer_problem="I think someone accessed my account",
            reason_for_escalation="Security-sensitive request",
        )
    )
    await db_session.commit()

    response = await client.get(
        f"/api/v1/support/tickets/{ticket.id}",
        headers={"Authorization": f"Bearer {security_staff_token}"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_ticket_queue_is_scoped_by_role(client, staff_token, security_staff_token, db_session):
    """spec §36/§52: the queue LISTING (not just the per-ticket check) must
    already exclude tickets a role isn't allowed to act on - a
    SUPPORT_AGENT should never even see a SECURITY-intent ticket in their
    queue, and a SECURITY_AGENT's queue should never show a general one."""
    from app.domain.models import SupportTicket
    from app.repositories.tickets import TicketRepository

    repo = TicketRepository(db_session, DEFAULT_TENANT_ID)
    general_customer_id, general_conversation_id = await _make_conversation(db_session, "general")
    await repo.create(
        SupportTicket(
            conversation_id=general_conversation_id,
            customer_id=general_customer_id,
            intent="REFUND",
            priority="HIGH",
            status="open",
            summary="Refund pending approval",
            customer_problem="Wants a refund",
            reason_for_escalation="High-risk action requires approval",
        )
    )
    sec_customer_id, sec_conversation_id = await _make_conversation(db_session, "sec3")
    await repo.create(
        SupportTicket(
            conversation_id=sec_conversation_id,
            customer_id=sec_customer_id,
            intent="SECURITY",
            priority="CRITICAL",
            status="open",
            summary="Suspicious login",
            customer_problem="I think someone accessed my account",
            reason_for_escalation="Security-sensitive request",
        )
    )
    await db_session.commit()

    agent_response = await client.get(
        "/api/v1/support/tickets", headers={"Authorization": f"Bearer {staff_token}"}
    )
    assert agent_response.status_code == 200
    agent_intents = {t["intent"] for t in agent_response.json()}
    assert "REFUND" in agent_intents
    assert "SECURITY" not in agent_intents

    security_response = await client.get(
        "/api/v1/support/tickets", headers={"Authorization": f"Bearer {security_staff_token}"}
    )
    assert security_response.status_code == 200
    security_intents = {t["intent"] for t in security_response.json()}
    assert "SECURITY" in security_intents
    assert "REFUND" not in security_intents


@pytest.mark.asyncio
async def test_only_admin_can_create_staff_users(client, staff_token, admin_staff_token):
    non_admin_resp = await client.post(
        "/api/v1/staff/users",
        json={"username": "new_agent_1", "password": "a-strong-password-123", "role": "SUPPORT_AGENT"},
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    assert non_admin_resp.status_code == 403

    admin_resp = await client.post(
        "/api/v1/staff/users",
        json={"username": "new_agent_2", "password": "a-strong-password-123", "role": "SUPPORT_AGENT"},
        headers={"Authorization": f"Bearer {admin_staff_token}"},
    )
    assert admin_resp.status_code == 201
    assert admin_resp.json()["role"] == "SUPPORT_AGENT"


@pytest.mark.asyncio
async def test_only_admin_can_list_staff_users(client, staff_token, admin_staff_token, seeded_admin):
    non_admin_resp = await client.get(
        "/api/v1/staff/users", headers={"Authorization": f"Bearer {staff_token}"}
    )
    assert non_admin_resp.status_code == 403

    admin_resp = await client.get(
        "/api/v1/staff/users", headers={"Authorization": f"Bearer {admin_staff_token}"}
    )
    assert admin_resp.status_code == 200
    usernames = {u["username"] for u in admin_resp.json()}
    assert seeded_admin["username"] in usernames
