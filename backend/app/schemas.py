from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, EmailStr, Field


DEFAULT_MODEL_CONFIG = "openai-codex/gpt-5.3-codex-spark"
DEFAULT_TEMPLATE_ID = "audit-codex-base"
DEFAULT_STACK = "openclaw"

STACK_REPOS = {
    "openclaw": "https://github.com/openclaw/openclaw",
    "zylos": "https://github.com/zylos-ai/zylos-core",
}

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
    template_id: str = Field(default=DEFAULT_TEMPLATE_ID)
    stack: str = Field(default=DEFAULT_STACK, pattern="^(openclaw|zylos)$")
    brief: Optional[str] = Field(default=None, max_length=1000)
    telegram_handle: Optional[str] = Field(default=None, max_length=120)


class TemplateConfig(BaseModel):
    id: str
    name: str
    description: str
    codex_profile: str
    notes: list[str] = []


class EmployeeResponse(BaseModel):
    id: str
    owner_id: str
    name: str
    role: str
    template_id: str
    stack: str = DEFAULT_STACK
    repo_url: str = STACK_REPOS[DEFAULT_STACK]
    brief: Optional[str] = None
    telegram_handle: Optional[str] = None
    employee_model_config: str = Field(alias="model_config")
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


class DashboardSummary(BaseModel):
    total: int
    ready: int
    waiting_bot_token: int
    provisioning: int
    failed: int


class DashboardResponse(BaseModel):
    owner: UserResponse
    summary: DashboardSummary


def get_default_templates() -> list[TemplateConfig]:
    return [
        TemplateConfig(
            id="audit-codex-base",
            name="Audit-Base Copilot",
            description="默认复用 audit 的 Codex 配置，适合通用研发/复核流程的AI员工。",
            codex_profile=DEFAULT_MODEL_CONFIG,
            notes=[
                "复制 audit 的默认模型配置",
                "附带日志与状态上报",
                "可作为默认模板直接发起 OpenClaw 初始化",
            ],
        ),
        TemplateConfig(
            id="ops-runner",
            name="Ops Runner",
            description="面向轻量运维任务的专属Agent，适合监控与流程触发。",
            codex_profile="openai-codex/gpt-5.3-codex",
            notes=["执行周期任务", "支持命令与脚本建议", "适配多账号运维场景"],
        ),
        TemplateConfig(
            id="ops-technical-writer",
            name="Tech Writer",
            description="适合撰写技术说明、日报和知识库条目。",
            codex_profile="openai-codex/gpt-5.3-codex",
            notes=["更强文本组织", "带进度记录建议", "可用于项目总结"],
        ),
    ]
