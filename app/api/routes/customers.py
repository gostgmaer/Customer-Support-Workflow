"""Customer self-service auth: register + login.

Public, self-serve registration only ever creates the customer in
DEFAULT_TENANT_ID - this is the public-facing storefront's auth, not a
multi-tenant provisioning flow (there is no way for a customer to name
their own tenant, by design - see docs/SECURITY.md). A B2B deployment that
needs customers scoped to a specific tenant would front this with a
tenant-specific login page/subdomain that passes a known tenant_id instead
of taking one from the request body.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.customer import (
    CustomerAuthResponse,
    CustomerLoginRequest,
    CustomerMeResponse,
    CustomerRegisterRequest,
)
from app.db.base import DEFAULT_TENANT_ID
from app.db.session import get_db
from app.domain.exceptions import AuthenticationError, ValidationError
from app.domain.models import Customer
from app.repositories.customers import CustomerRepository
from app.security.auth import create_access_token, get_current_customer
from app.security.passwords import hash_password, verify_password
from app.security.rate_limit import enforce_rate_limit

router = APIRouter(prefix="/api/v1/customers", tags=["customers"])

_LOGIN_ATTEMPT_LIMIT = 5
_LOGIN_ATTEMPT_WINDOW_SECONDS = 300


@router.post("/register", response_model=CustomerAuthResponse, status_code=201)
async def register(body: CustomerRegisterRequest, session: AsyncSession = Depends(get_db)) -> dict:
    repo = CustomerRepository(session, DEFAULT_TENANT_ID)
    existing = await repo.get_by_email(body.email)
    if existing is not None:
        raise ValidationError("An account with this email already exists")

    customer = Customer(
        email=body.email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
    )
    created = await repo.create(customer)
    await session.commit()
    token = create_access_token(created.id, tenant_id=DEFAULT_TENANT_ID)
    return {"access_token": token, "customer_id": created.id, "full_name": created.full_name}


@router.post("/login", response_model=CustomerAuthResponse)
async def login(body: CustomerLoginRequest, session: AsyncSession = Depends(get_db)) -> dict:
    await enforce_rate_limit(
        f"customer_login:{body.email}",
        limit=_LOGIN_ATTEMPT_LIMIT,
        window_seconds=_LOGIN_ATTEMPT_WINDOW_SECONDS,
    )
    repo = CustomerRepository(session, DEFAULT_TENANT_ID)
    customer = await repo.get_by_email(body.email)
    if (
        customer is None
        or customer.is_locked
        or not customer.password_hash
        or not verify_password(body.password, customer.password_hash)
    ):
        # Same error for "no such account", "wrong password", and "locked" -
        # never reveal which one it was (spec §23).
        raise AuthenticationError("Invalid email or password")
    token = create_access_token(customer.id, tenant_id=customer.tenant_id)
    return {"access_token": token, "customer_id": customer.id, "full_name": customer.full_name}


@router.get("/me", response_model=CustomerMeResponse)
async def me(
    customer: tuple[str, str] = Depends(get_current_customer), session: AsyncSession = Depends(get_db)
) -> Customer:
    customer_id, tenant_id = customer
    repo = CustomerRepository(session, tenant_id)
    record = await repo.get(customer_id)
    if record is None:
        raise AuthenticationError("Customer not found")
    return record
