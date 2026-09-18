"""Authentication (spec §23, §35-36): JWT-based auth for customers, staff,
and internal service-to-service calls.

Tokens are deliberately distinguished by a `scope` claim ("customer" /
"staff" / "system") so a leaked/misdirected token can never be accepted by
the wrong kind of endpoint even if a route wired the wrong dependency by
mistake - the decode function itself enforces scope, not just the
caller's choice of dependency. Every token also carries a `tenant_id`
claim (spec §43) - `DEFAULT_TENANT_ID` unless a real multi-tenant
deployment mints tokens with something else.

`create_access_token`/`decode_access_token` are also used directly by
tests and by scripts/seed to mint tokens for the seeded customers/staff.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Header

from app.config import get_settings
from app.db.base import DEFAULT_TENANT_ID
from app.domain.enums.role import ALL_STAFF_ROLES
from app.domain.exceptions import AuthenticationError, AuthorizationError

STAFF_ROLES = ALL_STAFF_ROLES


def _encode(payload: dict, *, expiry_minutes: int) -> str:
    settings = get_settings()
    full_payload = {
        **payload,
        "exp": datetime.now(UTC) + timedelta(minutes=expiry_minutes),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(full_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid access token") from exc


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError("Missing or malformed Authorization header")
    return authorization.split(" ", 1)[1]


# --- Customer tokens ---


def create_access_token(
    customer_id: str, *, tenant_id: str = DEFAULT_TENANT_ID, expiry_minutes: int | None = None
) -> str:
    settings = get_settings()
    expiry = expiry_minutes if expiry_minutes is not None else settings.jwt_expiry_minutes
    return _encode(
        {"sub": customer_id, "scope": "customer", "tenant_id": tenant_id}, expiry_minutes=expiry
    )


def decode_access_token(token: str) -> tuple[str, str]:
    """Returns (customer_id, tenant_id)."""
    payload = _decode(token)
    if payload.get("scope") != "customer":
        raise AuthenticationError("Token is not a valid customer access token")
    customer_id = payload.get("sub")
    if not customer_id:
        raise AuthenticationError("Access token missing subject")
    return customer_id, payload.get("tenant_id", DEFAULT_TENANT_ID)


async def get_current_customer(authorization: str | None = Header(default=None)) -> tuple[str, str]:
    """Returns (customer_id, tenant_id)."""
    return decode_access_token(_bearer_token(authorization))


async def get_current_customer_id(authorization: str | None = Header(default=None)) -> str:
    """Convenience wrapper for routes that only need the customer id, not
    the tenant (e.g. tenant isolation isn't relevant to that check)."""
    customer_id, _tenant_id = await get_current_customer(authorization)
    return customer_id


async def get_current_user(authorization: str | None = Header(default=None)) -> tuple[str, str, str]:
    """Returns (user_id, scope, tenant_id) - accepts EITHER a customer or a
    staff bearer token, unlike every other dependency in this module which
    enforces exactly one. For endpoints deliberately open to any
    authenticated user regardless of which portal they signed into (spec:
    the shared knowledge-base "ask" chat) - not a general-purpose
    replacement for the scope-specific dependencies above, which stay the
    right choice whenever an endpoint's data or side effects are
    inherently customer- or staff-only."""
    payload = _decode(_bearer_token(authorization))
    scope = payload.get("scope")
    tenant_id = payload.get("tenant_id", DEFAULT_TENANT_ID)
    if scope not in ("customer", "staff"):
        raise AuthenticationError("Token is not a valid customer or staff access token")
    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationError("Access token missing subject")
    return user_id, scope, tenant_id


# --- Staff tokens (spec §18/§26: ticket approve/reject is a separate trust
# boundary - see docs/SECURITY.md) ---


def create_staff_token(
    staff_id: str, *, role: str, tenant_id: str = DEFAULT_TENANT_ID, expiry_minutes: int | None = None
) -> str:
    settings = get_settings()
    expiry = expiry_minutes if expiry_minutes is not None else settings.jwt_expiry_minutes
    return _encode(
        {"sub": staff_id, "scope": "staff", "role": role, "tenant_id": tenant_id},
        expiry_minutes=expiry,
    )


def decode_staff_token(token: str) -> tuple[str, str, str]:
    """Returns (staff_id, role, tenant_id)."""
    payload = _decode(token)
    if payload.get("scope") != "staff":
        raise AuthenticationError("Token is not a valid staff access token")
    staff_id = payload.get("sub")
    role = payload.get("role")
    if not staff_id or not role:
        raise AuthenticationError("Staff token missing subject/role")
    return staff_id, role, payload.get("tenant_id", DEFAULT_TENANT_ID)


def require_staff_role(*allowed_roles: str):
    """FastAPI dependency factory: decodes the staff bearer token and
    checks its role is one of `allowed_roles`. Returns (staff_id, role, tenant_id).
    Pass no roles to accept any authenticated staff member regardless of role."""

    async def _dependency(authorization: str | None = Header(default=None)) -> tuple[str, str, str]:
        staff_id, role, tenant_id = decode_staff_token(_bearer_token(authorization))
        if allowed_roles and role not in allowed_roles:
            raise AuthorizationError(f"Role '{role}' is not permitted to perform this action")
        return staff_id, role, tenant_id

    return _dependency


# --- System tokens (spec §36: SYSTEM role) - internal service-to-service
# calls (scripts, scheduled jobs), never issued to an end user or agent. ---


def create_system_token(system_id: str, *, tenant_id: str = DEFAULT_TENANT_ID) -> str:
    settings = get_settings()
    return _encode(
        {"sub": system_id, "scope": "system", "tenant_id": tenant_id},
        expiry_minutes=settings.jwt_expiry_minutes,
    )


def decode_system_token(token: str) -> tuple[str, str]:
    """Returns (system_id, tenant_id)."""
    payload = _decode(token)
    if payload.get("scope") != "system":
        raise AuthenticationError("Token is not a valid system access token")
    system_id = payload.get("sub")
    if not system_id:
        raise AuthenticationError("System token missing subject")
    return system_id, payload.get("tenant_id", DEFAULT_TENANT_ID)
