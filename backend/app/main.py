from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db
from .repository import create_employee, create_user, get_employee_detail, list_employees_by_owner, save_bot_token_placeholder
from .schemas import CreateEmployeeRequest, EmployeeDetailResponse, EmployeeResponse, RegisterUserRequest, SaveBotTokenRequest, UserResponse


app = FastAPI(title="OpenClaw Hire API", version="0.1.0")

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


@app.get("/api/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/register", response_model=UserResponse)
def register_user(payload: RegisterUserRequest) -> UserResponse:
    return create_user(payload.name, payload.email, payload.company_name)


@app.post("/api/employees", response_model=EmployeeResponse)
def create_employee_job(payload: CreateEmployeeRequest) -> EmployeeResponse:
    return create_employee(
        owner_id=payload.owner_id,
        name=payload.name,
        role=payload.role,
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
