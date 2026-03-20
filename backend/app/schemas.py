from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator


# ── Auth ─────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    company_name: Optional[str] = None

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name cannot be empty.")
        return v.strip()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ── Users ─────────────────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    company_name: Optional[str] = None
    is_admin: bool = False
    created_at: str


# ── Catalog ───────────────────────────────────────────────────────────────────

class ProductCatalog(BaseModel):
    id: str
    name: str
    description: str
    tagline: str
    repo_url: str
    tags: list[str]
    features: list[str]


PRODUCTS: list[ProductCatalog] = [
    ProductCatalog(
        id="openclaw",
        name="OpenClaw",
        description="A self-hosted AI agent runtime with full audit logging, role-based access, and Docker-native deployment.",
        tagline="Open-source AI agent infrastructure",
        repo_url="https://github.com/openclaw/openclaw",
        tags=["AI", "Agents", "Self-hosted", "Audit"],
        features=[
            "Role-based agent access control",
            "Full audit trail and logging",
            "Docker Compose native deployment",
            "REST API for agent management",
            "Multi-tenant support",
        ],
    ),
    ProductCatalog(
        id="zylos",
        name="Zylos",
        description="A lightweight AI orchestration core built for high-throughput agent pipelines with minimal footprint.",
        tagline="AI orchestration built for scale",
        repo_url="https://github.com/zylos-ai/zylos-core",
        tags=["AI", "Orchestration", "Pipelines", "Lightweight"],
        features=[
            "High-throughput agent pipelines",
            "Minimal resource footprint",
            "Plugin-based architecture",
            "Built-in task scheduling",
            "Prometheus metrics endpoint",
        ],
    ),
]

PRODUCT_MAP = {p.id: p for p in PRODUCTS}


# ── Instances ─────────────────────────────────────────────────────────────────

class CreateInstanceRequest(BaseModel):
    name: str
    product: str

    @field_validator("product")
    @classmethod
    def valid_product(cls, v: str) -> str:
        if v not in PRODUCT_MAP:
            raise ValueError(f"Product must be one of: {list(PRODUCT_MAP.keys())}")
        return v

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Instance name cannot be empty.")
        return v.strip()


class InstallEventResponse(BaseModel):
    id: int
    state: str
    message: str
    created_at: str


class InstanceResponse(BaseModel):
    id: str
    owner_id: str
    name: str
    product: str
    repo_url: str
    status: str
    install_state: str
    compose_project: Optional[str] = None
    web_console_url: Optional[str] = None
    web_console_port: Optional[int] = None
    http_port: Optional[int] = None
    agent_name: Optional[str] = None
    is_telegram_configured: bool = False
    org_id: Optional[str] = None
    created_at: str
    updated_at: str


class InstanceConfigResponse(BaseModel):
    plugin_name: Optional[str] = None
    hub_url: Optional[str] = None
    org_id: Optional[str] = None
    # org_token intentionally excluded - sensitive credential, never expose to frontend
    agent_name: Optional[str] = None
    allow_group: bool = True
    allow_dm: bool = True
    configured_at: Optional[str] = None


class InstanceDetailResponse(BaseModel):
    instance: InstanceResponse
    install_timeline: list[InstallEventResponse]
    config: Optional[InstanceConfigResponse] = None


class ConfigureTelegramRequest(BaseModel):
    telegram_bot_token: str

    @field_validator("telegram_bot_token")
    @classmethod
    def token_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Telegram bot token cannot be empty.")
        return v.strip()


class ConfigureTelegramResponse(BaseModel):
    instance_id: str
    plugin_name: str
    hub_url: str
    org_id: str
    org_token: str
    agent_name: str
    message: str


class InstanceLogsResponse(BaseModel):
    instance_id: str
    compose_project: Optional[str] = None
    logs: str


class AdminUserInstancesResponse(BaseModel):
    user: UserResponse
    instances: list[InstanceResponse]


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardSummary(BaseModel):
    total: int
    running: int
    idle: int
    installing: int
    failed: int


class DashboardResponse(BaseModel):
    user: UserResponse
    summary: DashboardSummary
