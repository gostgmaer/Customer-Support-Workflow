from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SystemSettingItem(BaseModel):
    key: str
    value: Any
    source: str  # "override" | "default"
    updated_by: str | None = None
    updated_at: str | None = None


class UpdateSystemSettingRequest(BaseModel):
    value: Any
