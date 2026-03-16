from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException

from .database import get_connection
from .schemas import DEFAULT_MODEL_CONFIG, EmployeeDetailResponse, EmployeeResponse, StatusEventResponse, UserResponse


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def row_to_user(row) -> UserResponse:
    return UserResponse(**dict(row))


def row_to_employee(row) -> EmployeeResponse:
    return EmployeeResponse(**dict(row))


def create_user(name: str, email: str, company_name: str | None) -> UserResponse:
    user_id = f"user_{uuid4().hex[:12]}"
    created_at = utc_now()
    with get_connection() as connection:
        try:
            connection.execute(
                """
                INSERT INTO users (id, name, email, company_name, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, name, email.lower(), company_name, created_at),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Email already registered.") from exc
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return row_to_user(row)


def get_user_or_404(user_id: str):
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return row


def add_status_event(connection, employee_id: str, state: str, message: str, created_at: str) -> None:
    connection.execute(
        """
        INSERT INTO employee_status_events (employee_id, state, message, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (employee_id, state, message, created_at),
    )


def create_employee(owner_id: str, name: str, role: str, brief: str | None, telegram_handle: str | None) -> EmployeeResponse:
    get_user_or_404(owner_id)
    employee_id = f"emp_{uuid4().hex[:12]}"
    now = utc_now()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO employees (
                id, owner_id, name, role, brief, telegram_handle, model_config,
                current_state, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                employee_id,
                owner_id,
                name,
                role,
                brief,
                telegram_handle,
                DEFAULT_MODEL_CONFIG,
                "waiting_bot_token",
                now,
                now,
            ),
        )

        for state, message in (
            ("queued", "Employee provisioning requested."),
            ("preparing_workspace", "Workspace scaffold queued for creation."),
            ("writing_config", "Base OpenClaw config template prepared."),
            ("creating_service", "Runtime service definition drafted."),
            ("waiting_bot_token", "Waiting for Telegram bot token placeholder."),
        ):
            add_status_event(connection, employee_id, state, message, now)

        row = connection.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    return row_to_employee(row)


def list_employees_by_owner(owner_id: str) -> list[EmployeeResponse]:
    get_user_or_404(owner_id)
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM employees WHERE owner_id = ? ORDER BY created_at DESC", (owner_id,)
        ).fetchall()
    return [row_to_employee(row) for row in rows]


def get_employee_or_404(employee_id: str):
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    return row


def get_employee_detail(employee_id: str) -> EmployeeDetailResponse:
    employee = get_employee_or_404(employee_id)
    with get_connection() as connection:
        events = connection.execute(
            """
            SELECT state, message, created_at
            FROM employee_status_events
            WHERE employee_id = ?
            ORDER BY id ASC
            """,
            (employee_id,),
        ).fetchall()
    return EmployeeDetailResponse(
        employee=row_to_employee(employee),
        timeline=[StatusEventResponse(**dict(row)) for row in events],
    )


def save_bot_token_placeholder(employee_id: str, token_placeholder: str) -> EmployeeDetailResponse:
    get_employee_or_404(employee_id)
    now = utc_now()
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE employees
            SET telegram_bot_token_placeholder = ?, current_state = ?, updated_at = ?
            WHERE id = ?
            """,
            (token_placeholder, "ready", now, employee_id),
        )
        add_status_event(connection, employee_id, "ready", "Telegram placeholder saved. Employee scaffold ready.", now)
    return get_employee_detail(employee_id)
