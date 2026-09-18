"""Admin-only DB-backed runtime settings (spec §32/§43): lets an ADMIN tune
a small allow-list of operational settings per tenant
(`app.config.dynamic_settings.OVERRIDABLE_SETTINGS`) via the API instead of
an env var + redeploy. Secrets (API keys, JWT_SECRET, DATABASE_URL) are
never part of this allow-list and can never be set this way - see
docs/SECURITY.md.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.system_settings import SystemSettingItem, UpdateSystemSettingRequest
from app.config import get_settings
from app.config.dynamic_settings import (
    OVERRIDABLE_SETTINGS,
    invalidate_effective_settings_cache,
    validate_setting,
)
from app.db.session import get_db
from app.domain.exceptions import ValidationError
from app.repositories.system_settings import SystemSettingRepository
from app.security.auth import require_staff_role

router = APIRouter(prefix="/api/v1/admin/settings", tags=["admin"])

RequireAdmin = Depends(require_staff_role("ADMIN"))


@router.get("", response_model=list[SystemSettingItem])
async def list_settings(
    session: AsyncSession = Depends(get_db), admin: tuple[str, str, str] = RequireAdmin
) -> list[dict]:
    _admin_id, _role, tenant_id = admin
    overrides = {row.key: row for row in await SystemSettingRepository(session, tenant_id).list()}
    settings = get_settings()
    items = []
    for key in sorted(OVERRIDABLE_SETTINGS):
        row = overrides.get(key)
        if row is not None:
            items.append(
                {
                    "key": key,
                    "value": json.loads(row.value),
                    "source": "override",
                    "updated_by": row.updated_by,
                    "updated_at": row.updated_at.isoformat(),
                }
            )
        else:
            items.append({"key": key, "value": getattr(settings, key), "source": "default"})
    return items


@router.put("/{key}", response_model=SystemSettingItem)
async def update_setting(
    key: str,
    body: UpdateSystemSettingRequest,
    session: AsyncSession = Depends(get_db),
    admin: tuple[str, str, str] = RequireAdmin,
) -> dict:
    admin_id, _role, tenant_id = admin
    validate_setting(key, body.value)
    row = await SystemSettingRepository(session, tenant_id).upsert(
        key, json.dumps(body.value), updated_by=admin_id
    )
    await session.commit()
    invalidate_effective_settings_cache(tenant_id)
    return {
        "key": key,
        "value": json.loads(row.value),
        "source": "override",
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat(),
    }


@router.delete("/{key}", status_code=204)
async def delete_setting(
    key: str, session: AsyncSession = Depends(get_db), admin: tuple[str, str, str] = RequireAdmin
) -> None:
    _admin_id, _role, tenant_id = admin
    if key not in OVERRIDABLE_SETTINGS:
        raise ValidationError(f"'{key}' is not an overridable setting")
    await SystemSettingRepository(session, tenant_id).delete(key)
    await session.commit()
    invalidate_effective_settings_cache(tenant_id)
