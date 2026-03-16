from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, EmailStr, Field


DEFAULT_MODEL_CONFIG = "openai-codex/gpt-5.3-codex-spark"
INIT_STATES = (
    "queued",
    "preparing_workspace",
    "writing_config",
    "creating_service",
    "waiting_bot_token",
    "ready",
    "failed",
)


class RegisterUserRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    company_name: Optional[str] = Field(default=None, max_length=120)


class UserResponse(BaseModel):
    id: str
    name: str
    email: EmailStr
    company_name: Optional[str] = None
    created_at: str


class CreateEmployeeRequest(BaseModel):
    owner_id: str
    name: str = Field(min_length=2, max_length=80)
    role: str = Field(min_length=2, max_length=120)
    brief: Optional[str] = Field(default=None, max_length=1000)
    telegram_handle: Optional[str] = Field(default=None, max_length=120)


class EmployeeResponse(BaseModel):
    id: str
    owner_id: str
    name: str
    role: str
    brief: Optional[str] = None
    telegram_handle: Optional[str] = None
    model_config: str
    current_state: str
    created_at: str
    updated_at: str
    telegram_bot_token_placeholder: Optional[str] = None


class StatusEventResponse(BaseModel):
    state: str
    message: str
    created_at: str


class EmployeeDetailResponse(BaseModel):
    employee: EmployeeResponse
    timeline: list[StatusEventResponse]


class SaveBotTokenRequest(BaseModel):
    telegram_bot_token_placeholder: str = Field(min_length=8, max_length=255)
