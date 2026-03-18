from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db
from .repository import (
    create_employee,
    create_template_table_safe,
    dashboard_for_owner,
    get_employee_detail,
    list_employees_by_owner,
    save_bot_token_placeholder,
)
from .schemas import (
    CreateEmployeeRequest,
    DashboardResponse,
    DashboardSummary,
    EmployeeDetailResponse,
    EmployeeResponse,
    RegisterUserRequest,
    SaveBotTokenRequest,
    TemplateConfig,
    UserResponse,
    get_default_templates,
)

app = FastAPI(title="OpenClaw Hire API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    create_template_table_safe()


@app.get("/api/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/templates", response_model=list[TemplateConfig])
def list_templates() -> list[TemplateConfig]:
    return get_default_templates()


@app.get("/api/dashboard/{owner_id}", response_model=DashboardResponse)
def get_owner_dashboard(owner_id: str) -> DashboardResponse:
    return dashboard_for_owner(owner_id)


@app.post("/api/register", response_model=UserResponse)
def register_user(payload: RegisterUserRequest) -> UserResponse:
    from .repository import create_user

    return create_user(payload.name, payload.email, payload.company_name)


@app.post("/api/employees", response_model=EmployeeResponse)
def create_employee_job(payload: CreateEmployeeRequest) -> EmployeeResponse:
    return create_employee(
        owner_id=payload.owner_id,
        name=payload.name,
        role=payload.role,
        template_id=payload.template_id,
        stack=payload.stack,
        brief=payload.brief,
        telegram_handle=payload.telegram_handle,
    )


@app.get("/api/owners/{owner_id}/employees", response_model=list[EmployeeResponse])
def list_owner_employees(owner_id: str) -> list[EmployeeResponse]:
    return list_employees_by_owner(owner_id)


@app.get("/api/employees/{employee_id}/status", response_model=EmployeeDetailResponse)
def get_init_status_timeline(employee_id: str) -> EmployeeDetailResponse:
    return get_employee_detail(employee_id)


@app.post("/api/employees/{employee_id}/bot-token", response_model=EmployeeDetailResponse)
def save_telegram_bot_token_placeholder(employee_id: str, payload: SaveBotTokenRequest) -> EmployeeDetailResponse:
    return save_bot_token_placeholder(employee_id, payload.telegram_bot_token_placeholder)
