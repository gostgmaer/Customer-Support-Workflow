from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.staff import (
    CreateStaffUserRequest,
    StaffLoginRequest,
    StaffLoginResponse,
    StaffUserResponse,
)
from app.db.session import get_db
from app.domain.exceptions import AuthenticationError, ValidationError
from app.domain.models import StaffUser
from app.repositories.staff import StaffRepository
from app.security.auth import create_staff_token, require_staff_role
from app.security.passwords import hash_password, verify_password
from app.security.rate_limit import enforce_rate_limit

router = APIRouter(prefix="/api/v1/staff", tags=["staff"])

# Tighter than the default request rate limit - login attempts are a brute-force target.
_LOGIN_ATTEMPT_LIMIT = 5
_LOGIN_ATTEMPT_WINDOW_SECONDS = 300

RequireAdmin = Depends(require_staff_role("ADMIN"))


@router.post("/login", response_model=StaffLoginResponse)
async def login(body: StaffLoginRequest, session: AsyncSession = Depends(get_db)) -> dict:
    await enforce_rate_limit(
        f"staff_login:{body.username}",
        limit=_LOGIN_ATTEMPT_LIMIT,
        window_seconds=_LOGIN_ATTEMPT_WINDOW_SECONDS,
    )
    staff = await StaffRepository(session).get_by_username(body.username)
    if staff is None or not staff.is_active or not verify_password(body.password, staff.password_hash):
        # Same error for "no such user" and "wrong password" - never reveal
        # which one it was (spec §23: don't leak account-existence info).
        raise AuthenticationError("Invalid username or password")
    token = create_staff_token(staff.id, role=staff.role, tenant_id=staff.tenant_id)
    return {"access_token": token, "role": staff.role}


@router.get("/users", response_model=list[StaffUserResponse])
async def list_staff_users(
    session: AsyncSession = Depends(get_db), admin: tuple[str, str, str] = RequireAdmin
) -> list[StaffUser]:
    _admin_id, _role, tenant_id = admin
    return await StaffRepository(session).list_by_tenant(tenant_id)


@router.post("/users", response_model=StaffUserResponse, status_code=201)
async def create_staff_user(
    body: CreateStaffUserRequest,
    session: AsyncSession = Depends(get_db),
    admin: tuple[str, str, str] = RequireAdmin,
) -> StaffUser:
    """ADMIN-only (spec §36): creates a staff account with any role, in the
    calling admin's own tenant. Without this, RBAC would only be
    exercisable via the seed script - see docs/SECURITY.md."""
    _admin_id, _role, tenant_id = admin
    existing = await StaffRepository(session).get_by_username(body.username)
    if existing is not None:
        raise ValidationError(f"Username '{body.username}' is already taken")

    staff = StaffUser(
        tenant_id=tenant_id,
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role.value,
        is_active=True,
    )
    created = await StaffRepository(session).create(staff)
    await session.commit()
    return created
