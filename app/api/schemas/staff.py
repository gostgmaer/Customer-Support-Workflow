from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.enums.role import StaffRole


class StaffLoginRequest(BaseModel):
    username: str
    password: str


class StaffLoginResponse(BaseModel):
    access_token: str
    role: str


class CreateStaffUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=12)
    role: StaffRole


class StaffUserResponse(BaseModel):
    id: str
    username: str
    role: str
    is_active: bool
    created_at: datetime
