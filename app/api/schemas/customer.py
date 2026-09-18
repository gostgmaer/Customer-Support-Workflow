from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class CustomerRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    full_name: str = Field(min_length=1, max_length=200)


class CustomerLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class CustomerAuthResponse(BaseModel):
    access_token: str
    customer_id: str
    full_name: str


class CustomerMeResponse(BaseModel):
    id: str
    email: str
    full_name: str
    tier: str
